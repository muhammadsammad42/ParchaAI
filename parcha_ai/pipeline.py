"""
End-to-end prescription processing pipeline for ParchaAI.

This module orchestrates the complete workflow:
1. Image preprocessing
2. Two-pass extraction (Gemini Vision)
3. Text normalization
4. Database validation (RapidFuzz + OpenFDA)
5. Confidence scoring and routing
6. Fallback verification with Groq Vision (if needed)
7. Final validation and response generation
"""

import asyncio
import logging
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from .config import get_config
from .confidence import FallbackRouter
from .extraction import (
    GeminiVisionExtractor,
    GroqFallbackExtractor,
    parse_json_response,
)
from .fuzzy_match import MedicineMatcher
from .openfda import OpenFDAClient
from .preprocessing import get_image_info, is_valid_image_file
from .utils import normalize_field, normalize_text
from .validation import MedicineDetail, PrescriptionResponse

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Custom exception for pipeline errors."""
    pass


class ParchaAIPipeline:
    """
    Complete prescription extraction and validation pipeline.
    
    This class coordinates all components:
    - Image loading and validation
    - Vision model extraction
    - Database matching and enrichment
    - Confidence evaluation
    - Fallback routing
    - Final response generation
    
    Attributes
    ----------
    extractor : GeminiVisionExtractor
        Primary vision model extractor
    fallback_extractor : GroqFallbackExtractor
        Fallback vision model
    matcher : MedicineMatcher
        Local database matcher
    fda_client : OpenFDAClient
        OpenFDA API client
    router : FallbackRouter
        Confidence-based routing logic
    """
    
    def __init__(
        self,
        confidence_threshold: Optional[float] = None,
        fuzzy_score_cutoff: Optional[int] = None,
        name_correction_cutoff: int = 96
    ):
        """
        Initialize the pipeline with all components.
        
        Parameters
        ----------
        confidence_threshold : float, optional
            Confidence threshold for fallback routing, by default 0.80 (was 0.85)
        fuzzy_score_cutoff : int, optional
            RapidFuzz score cutoff (0-100), by default 85
            Score >= 85: Accept match and enrich composition/uses/side_effects/manufacturer
            Score < 85: Reject match and apply UNIDENTIFIED DRUG SAFETY RULE
        name_correction_cutoff : int, optional
            Separate, stricter score cutoff (0-100) required before overwriting the
            extracted medicine_name with the database's "official" name, by default 96.
            Enrichment data (composition/side_effects/etc.) can tolerate a looser
            match, but replacing the name the extraction actually saw needs to be
            near-certain, otherwise unrelated drugs get swapped in (e.g. "Morphine"
            incorrectly renamed to an unrelated tablet just because they scored 90
            on a loose fuzzy comparison).
        """
        logger.info("Initializing ParchaAI Pipeline")
        
        config = get_config()
        confidence_threshold = (
            config.confidence_threshold
            if confidence_threshold is None else confidence_threshold
        )
        fuzzy_score_cutoff = (
            config.fuzzy_match_threshold
            if fuzzy_score_cutoff is None else fuzzy_score_cutoff
        )

        # Initialize components with centralized configuration values.
        self.extractor = GeminiVisionExtractor()
        self.fallback_extractor = GroqFallbackExtractor()
        self.matcher = MedicineMatcher(score_cutoff=fuzzy_score_cutoff)
        self.fda_client = OpenFDAClient()
        self.router = FallbackRouter(confidence_threshold=confidence_threshold)
        self.fuzzy_score_cutoff = fuzzy_score_cutoff
        self.name_correction_cutoff = name_correction_cutoff
        
        logger.info(f"Pipeline initialized: fuzzy_score_cutoff={fuzzy_score_cutoff}, "
                   f"name_correction_cutoff={name_correction_cutoff}, "
                   f"confidence_threshold={confidence_threshold}")
        logger.info("Pipeline initialization complete")
    
    async def process_image(
        self,
        image_path: Union[str, Path],
        skip_fallback: bool = False
    ) -> PrescriptionResponse:
        """
        Process a prescription image end-to-end.
        
        Parameters
        ----------
        image_path : str or Path
            Path to prescription image
        skip_fallback : bool, optional
            Skip fallback verification even if confidence is low, by default False
        
        Returns
        -------
        PrescriptionResponse
            Complete validated prescription data
        
        Raises
        ------
        PipelineError
            If processing fails at any stage
        
        Examples
        --------
        >>> pipeline = ParchaAIPipeline()
        >>> result = await pipeline.process_image("prescription.jpg")
        >>> print(f"Found {len(result.extracted_medicines)} medicines")
        """
        image_path = Path(image_path)
        start_time = time.time()
        
        logger.info(f"{'='*60}")
        logger.info(f"Processing: {image_path.name}")
        logger.info(f"{'='*60}")
        
        # Step 1: Validate image
        logger.info("Step 1: Validating image")
        if not is_valid_image_file(image_path):
            raise PipelineError(f"Invalid image file: {image_path}")
        
        image_info = get_image_info(image_path)
        logger.info(
            f"Image info: {image_info['width']}x{image_info['height']} pixels, "
            f"{image_info['size_mb']} MB"
        )
        
        # Step 2: Extract with primary model
        logger.info("Step 2: Primary extraction (Gemini Vision)")
        json_response, timings = await self.extractor.extract(image_path)
        raw_medicines = parse_json_response(json_response)

        logger.info(f"Extracted {len(raw_medicines)} medicine(s)")
        
        # Step 3: Normalize and validate
        logger.info("Step 3: Text normalization and database validation")
        medicines, fuzzy_scores = await self._validate_medicines(raw_medicines)
        
        # Step 4: Calculate confidence
        logger.info("Step 4: Confidence evaluation")
        should_fallback, primary_confidence = self.router.evaluate_and_route(
            medicines,
            fuzzy_scores
        )
        
        logger.info(f"Primary confidence: {primary_confidence:.3f}")
        
        # Step 5: Fallback if needed
        used_fallback = False
        if should_fallback and not skip_fallback:
            logger.info("Step 5: Triggering fallback verification")
            medicines, used_fallback = await self._execute_fallback(
                image_path,
                medicines,
                len(raw_medicines),
                fuzzy_scores
            )
        else:
            logger.info("Step 5: Skipped (confidence sufficient or disabled)")
            # Finalize without fallback
            medicines = self.router.finalize_medicines(medicines, fuzzy_scores)
        
        # ----- NEW: Filter out likely hallucinations -----
        medicines = self._filter_medicines(medicines)
        # -------------------------------------------------
        
        # Step 6: Generate response
        logger.info("Step 6: Generating final response")
        total_time = time.time() - start_time
        
        response = PrescriptionResponse(
            prescription_id=image_path.stem,
            image_path=str(image_path),
            extracted_medicines=medicines,
            extraction_time_seconds=round(total_time, 3),
            fallback_model_used=used_fallback
        )
        
        logger.info(f"{'='*60}")
        logger.info(f"Pipeline complete in {total_time:.2f}s")
        logger.info(
            f"Result: {len(medicines)} medicine(s), "
            f"confidence: {primary_confidence:.3f}"
        )
        logger.info(f"{'='*60}\n")
        
        return response
    
    async def _validate_medicines(
        self,
        raw_medicines: List[Dict]
    ) -> Tuple[List[MedicineDetail], Dict[str, float]]:
        """
        Validate and enrich medicines with database data.
        
        Parameters
        ----------
        raw_medicines : list of dict
            Raw extracted medicine data
        
        Returns
        -------
        tuple of (list, dict)
            Validated MedicineDetail objects and fuzzy match scores
        """
        validated_medicines = []
        fuzzy_scores = {}

        async def _process_single_med(raw_med: Dict) -> Optional[MedicineDetail]:
            medicine_name = normalize_text(raw_med.get('medicine_name', 'unread'))
            dosage = normalize_field('dosage', raw_med.get('dosage', 'unread'))
            frequency = normalize_field('frequency', raw_med.get('frequency', 'unread'))
            duration = normalize_field('duration', raw_med.get('duration', 'unread'))
            purpose = normalize_text(raw_med.get('purpose', 'unread'))

            # The extraction prompt explicitly tells the model to write
            # "unread" for medicine_name when a line is illegible (this is
            # intentional anti-hallucination behavior -- see prompts.py
            # EXAMPLE 5 "Exclude Uncertain Lines"). But MedicineDetail's
            # validator forbids medicine_name="unread". Previously that
            # ValidationError was never caught here, so it propagated all
            # the way up through _validate_medicines -> process_image and
            # crashed the ENTIRE image -- discarding every other correctly
            # read medicine on the same prescription along with it. Since
            # the model already told us it couldn't read this one line, the
            # correct behavior is to drop just this entry and keep going,
            # not to lose the whole image.
            if medicine_name == 'unread':
                logger.warning(
                    "Dropping one medicine entry with unread medicine_name "
                    "(model flagged it illegible) -- other medicines on "
                    "this image are still processed normally."
                )
                return None

            # FIX: the extraction prompt explicitly asks the model for a
            # self-assessed confidence per medicine ("Low (0.0-0.5): Difficult
            # handwriting, multiple 'unread' fields"). That's the one signal
            # that actually reflects OCR/handwriting legibility. Previously it
            # was read here and then discarded (confidence was hardcoded to
            # 0.0 below), so the final confidence score -- and therefore the
            # hallucination filter -- never had access to it at all and relied
            # almost entirely on database-lookup success instead. Parse it
            # defensively since it's LLM-provided and may be missing, a
            # string, or out of range.
            raw_confidence = raw_med.get('confidence', 0.5)
            try:
                extraction_confidence = float(raw_confidence)
            except (TypeError, ValueError):
                extraction_confidence = 0.5
            extraction_confidence = max(0.0, min(1.0, extraction_confidence))

            try:
                base_medicine = MedicineDetail(
                    medicine_name=medicine_name,
                    dosage=dosage,
                    frequency=frequency,
                    duration=duration,
                    purpose=purpose,
                    composition='unread',
                    uses='unread',
                    side_effects='unread',
                    precautions='unread',
                    manufacturer='unread',
                    confidence=0.0,
                    extraction_confidence=extraction_confidence,
                    found_in_local_db=False,
                    found_in_openfda=False,
                    low_confidence=False,
                    requires_human_review=False
                )
            except Exception as e:
                # Defensive catch-all: any other unexpected validation
                # failure on a single medicine should not take down the
                # whole image either.
                logger.error(f"Skipping unprocessable medicine entry: {e}")
                return None

            logger.debug(f"Matching: {medicine_name}")
            local_match_task = asyncio.to_thread(self.matcher.match_medicine, medicine_name)
            enrichment_task = self.fda_client.enrich_medicine(base_medicine)
            match_result, enrichment_medicine = await asyncio.gather(
                local_match_task,
                enrichment_task
            )

            # Only trust a local DB match's *identity* -- and therefore its
            # composition/uses/side_effects/manufacturer data -- once the
            # score clears name_correction_cutoff (96). Below that, the
            # matcher can pick an unrelated drug that happens to share
            # leftover word fragments after normalization (e.g.
            # "Azithromycin" -> "MY 360 Tablet" at score 90). Previously
            # this code refused to rename the medicine at that range but
            # STILL copied composition/uses/side_effects/manufacturer from
            # that same uncertain match -- silently attaching one drug's
            # medical info to a different drug's name. A score below the
            # identity threshold means we're not confident it's the same
            # drug at all, so none of its fields are trustworthy either.
            high_confidence_match = (
                match_result and match_result['match_score'] >= self.name_correction_cutoff
            )

            if high_confidence_match:
                logger.info(
                    f"Local DB match: '{medicine_name}' -> "
                    f"'{match_result['official_name']}' (score: {match_result['match_score']})"
                )

                medicine = base_medicine.model_copy(deep=True)
                medicine.medicine_name = match_result['official_name']
                medicine.composition = match_result.get('composition', 'unread')
                medicine.uses = match_result.get('uses', 'unread')
                medicine.side_effects = match_result.get('side_effects', 'unread')
                medicine.precautions = match_result.get('precautions', 'unread')
                medicine.manufacturer = match_result.get('manufacturer', 'unread')
                medicine.found_in_local_db = True

                if enrichment_medicine.found_in_openfda:
                    if medicine.precautions == 'unread' and enrichment_medicine.precautions != 'unread':
                        medicine.precautions = enrichment_medicine.precautions
                    if medicine.side_effects == 'unread' and enrichment_medicine.side_effects != 'unread':
                        medicine.side_effects = enrichment_medicine.side_effects
                    if medicine.purpose == 'unread' and enrichment_medicine.purpose != 'unread':
                        medicine.purpose = enrichment_medicine.purpose
                    medicine.found_in_openfda = True

                fuzzy_scores[medicine.medicine_name] = match_result['match_score']
                return medicine

            if match_result and match_result['match_score'] >= self.fuzzy_score_cutoff:
                # Real signal worth keeping for confidence scoring (the name
                # is *somewhat* similar to something in the DB), but not
                # confident enough to borrow that entry's medical data.
                logger.info(
                    f"Match score {match_result['match_score']} for '{medicine_name}' below "
                    f"name_correction_cutoff={self.name_correction_cutoff} - not trusting "
                    f"'{match_result['official_name']}''s data (identity unconfirmed); "
                    f"keeping extraction-only fields and falling back to OpenFDA"
                )
                fuzzy_scores[medicine_name] = match_result['match_score']

            if enrichment_medicine.found_in_openfda:
                logger.info(f"OpenFDA enrichment found for '{medicine_name}'")
                return enrichment_medicine

            logger.warning(
                f"Medicine '{medicine_name}' not found in local DB or OpenFDA - "
                f"flagging for review"
            )
            medicine = base_medicine.model_copy(deep=True)
            medicine.composition = 'unread'
            medicine.uses = 'unread'
            medicine.side_effects = 'unread'
            medicine.precautions = 'unread'
            medicine.manufacturer = 'unread'
            medicine.low_confidence = True
            medicine.requires_human_review = True
            return medicine

        if raw_medicines:
            processed_medicines = await asyncio.gather(
                *[_process_single_med(raw_med) for raw_med in raw_medicines]
            )
            # Drop the None placeholders for medicines that were skipped
            # (unread name or other unprocessable entry) above.
            validated_medicines = [m for m in processed_medicines if m is not None]

        return validated_medicines, fuzzy_scores
    
    async def _execute_fallback(
        self,
        image_path: Path,
        primary_medicines: List[MedicineDetail],
        medicine_count: int,
        fuzzy_scores: Dict[str, float]
    ) -> Tuple[List[MedicineDetail], bool]:
        """
        Execute fallback verification with Groq.
        
        Parameters
        ----------
        image_path : Path
            Prescription image path
        primary_medicines : list of MedicineDetail
            Primary extraction results
        medicine_count : int
            Expected medicine count
        fuzzy_scores : dict
            Primary fuzzy scores
        
        Returns
        -------
        tuple of (list, bool)
            Final medicines and whether fallback was used
        """
        # Send only extraction fields: enrichment may be stale or unrelated to
        # what is visibly written and should never bias the visual verifier.
        previous_medicines = [
            {
                key: med.model_dump().get(key, 'unread')
                for key in ('medicine_name', 'dosage', 'frequency', 'duration', 'purpose', 'confidence')
            }
            for med in primary_medicines
        ]
        fallback_response, fallback_time = await self.fallback_extractor.verify_extraction(
            image_path,
            medicine_count=medicine_count,
            previous_medicines=previous_medicines,
            confidence_threshold=self.router.scorer.threshold,
        )
        
        if not fallback_response:
            logger.warning("Fallback extraction failed - using primary results with flags")
            final_medicines = self.router.finalize_medicines(
                primary_medicines,
                fuzzy_scores
            )
            return final_medicines, False
        
        # Parse fallback response
        try:
            fallback_raw = parse_json_response(fallback_response)
            
            # Validate fallback medicines
            fallback_medicines, fallback_fuzzy_scores = await self._validate_medicines(
                fallback_raw
            )
            
            # Compare and merge (use the validated/enriched fallback medicines,
            # not the raw unvalidated dicts, so a "fallback wins" decision
            # actually carries over composition/uses/side_effects/precautions too)
            final_medicines, fallback_better = self.router.merge_fallback_results(
                primary_medicines=primary_medicines,
                fallback_medicines=fallback_medicines,
                fuzzy_scores_primary=fuzzy_scores,
                fuzzy_scores_fallback=fallback_fuzzy_scores
            )
            
            return final_medicines, fallback_better
        
        except Exception as e:
            logger.error(f"Failed to process fallback results: {e}")
            final_medicines = self.router.finalize_medicines(
                primary_medicines,
                fuzzy_scores
            )
            return final_medicines, False
    
    def _filter_medicines(self, medicines: List[MedicineDetail]) -> List[MedicineDetail]:
        """
        Remove likely hallucinations.

        FIX: previously this dropped anything not found in local DB/OpenFDA
        with computed confidence < 0.6. Because the old confidence formula
        gave database presence ~70% combined weight (db-match + fuzzy-score
        factors), that 0.6 cutoff was, in practice, almost impossible for a
        real-but-undatabased medicine to clear -- local/regional brand names
        not present in an 11k-row reference CSV or in OpenFDA were being
        deleted wholesale regardless of how legibly they were written,
        directly capping recall.

        Now that `medicine.extraction_confidence` carries the model's own
        self-reported read-confidence (see MedicineDetail / prompts.py), we
        use THAT as the actual hallucination signal: a medicine is only
        dropped when the model itself was unsure about it AND no database
        corroborates it. A medicine the model read confidently is kept even
        if no database happens to carry that brand -- that's a database
        coverage gap, not evidence of hallucination.
        """
        filtered = []
        for med in medicines:
            # Database corroboration is always sufficient to keep.
            if med.found_in_local_db or med.found_in_openfda:
                filtered.append(med)
                continue
            # No DB corroboration: keep unless the MODEL ITSELF was unsure.
            # (0.4 chosen to match the extraction prompt's own "Low
            # (0.0-0.5): Difficult handwriting" band -- below that the model
            # is telling us it likely couldn't read this reliably.)
            if med.extraction_confidence >= 0.4:
                filtered.append(med)
            else:
                logger.warning(
                    f"Dropping likely-hallucinated medicine: {med.medicine_name} "
                    f"(model's own extraction_confidence={med.extraction_confidence:.2f}, "
                    f"no database corroboration)"
                )
        return filtered
    
    async def process_batch(
        self,
        image_paths: List[Union[str, Path]],
        skip_fallback: bool = False
    ) -> List[PrescriptionResponse]:
        """
        Process multiple prescriptions in batch.
        
        Parameters
        ----------
        image_paths : list of str or Path
            List of prescription image paths
        skip_fallback : bool, optional
            Skip fallback for all images, by default False
        
        Returns
        -------
        list of PrescriptionResponse
            Results for all images
        
        Examples
        --------
        >>> pipeline = ParchaAIPipeline()
        >>> results = await pipeline.process_batch(["rx_01.jpg", "rx_02.jpg"])
        >>> print(f"Processed {len(results)} prescriptions")
        """
        logger.info(f"Starting batch processing: {len(image_paths)} image(s)")
        
        results = []
        for image_path in image_paths:
            try:
                result = await self.process_image(image_path, skip_fallback)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to process {image_path}: {e}")
                # Continue with next image
                continue
        
        logger.info(f"Batch processing complete: {len(results)}/{len(image_paths)} succeeded")
        return results
    
    def get_statistics(self, response: PrescriptionResponse) -> Dict:
        """
        Get summary statistics for a prescription response.
        
        Parameters
        ----------
        response : PrescriptionResponse
            Prescription response
        
        Returns
        -------
        dict
            Statistics summary
        """
        medicines = response.extracted_medicines
        
        stats = {
            'total_medicines': len(medicines),
            'found_in_local_db': sum(1 for m in medicines if m.found_in_local_db),
            'found_in_openfda': sum(1 for m in medicines if m.found_in_openfda),
            'not_found': sum(
                1 for m in medicines
                if not m.found_in_local_db and not m.found_in_openfda
            ),
            'low_confidence': sum(1 for m in medicines if m.low_confidence),
            'requires_review': sum(1 for m in medicines if m.requires_human_review),
            'avg_confidence': (
                sum(m.confidence for m in medicines) / len(medicines)
                if medicines else 0.0
            ),
            'processing_time': response.extraction_time_seconds,
            'used_fallback': response.fallback_model_used
        }
        
        return stats


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def quick_process(
    image_path: Union[str, Path]
) -> PrescriptionResponse:
    """
    Quick single-image processing.
    
    Parameters
    ----------
    image_path : str or Path
        Prescription image path
    
    Returns
    -------
    PrescriptionResponse
        Complete prescription data
    
    Examples
    --------
    >>> result = await quick_process("prescription.jpg")
    >>> print(result.model_dump_json(indent=2))
    """
    pipeline = ParchaAIPipeline()
    return await pipeline.process_image(image_path)


async def process_prescription_sync_wrapper(image_path: Union[str, Path]) -> PrescriptionResponse:
    """
    Wrapper for running pipeline in synchronous code.
    
    Parameters
    ----------
    image_path : str or Path
        Prescription image path
    
    Returns
    -------
    PrescriptionResponse
        Complete prescription data
    
    Examples
    --------
    >>> # From synchronous code
    >>> import asyncio
    >>> result = asyncio.run(process_prescription_sync_wrapper("rx.jpg"))
    """
    return await quick_process(image_path)