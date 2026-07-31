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
from .medical_text_summarizer import summarize_uses_precautions
from .openfda import OpenFDAClient
from .preprocessing import get_image_info, is_valid_image_file
from .utils import normalize_field, normalize_text
from .validation import MedicineDetail, PrescriptionResponse

logger = logging.getLogger(__name__)


class PipelineError(Exception):
    """Custom exception for pipeline errors."""
    pass


class ParchaAIPipeline:

    
    def __init__(
        self,
        confidence_threshold: Optional[float] = None,
        fuzzy_score_cutoff: Optional[int] = None,
        name_correction_cutoff: int = 96
    ):
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
        
        medicines = self._filter_medicines(medicines)
        
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
        
        # Step 7: Post-process — generate Urdu summaries for side_effects/precautions
        logger.info("Step 7: Generating Urdu summaries for side_effects/precautions")
        self._populate_urdu_summaries(response.extracted_medicines)
        
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

        validated_medicines = []
        fuzzy_scores = {}

        async def _process_single_med(raw_med: Dict) -> Optional[MedicineDetail]:
            medicine_name = normalize_text(raw_med.get('medicine_name', 'unread'))
            dosage = normalize_field('dosage', raw_med.get('dosage', 'unread'))
            frequency = normalize_field('frequency', raw_med.get('frequency', 'unread'))
            duration = normalize_field('duration', raw_med.get('duration', 'unread'))
            purpose = normalize_text(raw_med.get('purpose', 'unread'))

            if medicine_name == 'unread':
                logger.warning(
                    "Dropping one medicine entry with unread medicine_name "
                    "(model flagged it illegible) -- other medicines on "
                    "this image are still processed normally."
                )
                return None
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
                logger.error(f"Skipping unprocessable medicine entry: {e}")
                return None

            logger.debug(f"Matching: {medicine_name}")
            local_match_task = asyncio.to_thread(self.matcher.match_medicine, medicine_name)
            enrichment_task = self.fda_client.enrich_medicine(base_medicine)
            match_result, enrichment_medicine = await asyncio.gather(
                local_match_task,
                enrichment_task
            )

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
            validated_medicines = [m for m in processed_medicines if m is not None]

        return validated_medicines, fuzzy_scores
    
    async def _execute_fallback(
        self,
        image_path: Path,
        primary_medicines: List[MedicineDetail],
        medicine_count: int,
        fuzzy_scores: Dict[str, float]
    ) -> Tuple[List[MedicineDetail], bool]:

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
        filtered = []
        for med in medicines:
            # Database corroboration is always sufficient to keep.
            if med.found_in_local_db or med.found_in_openfda:
                filtered.append(med)
                continue

            if med.extraction_confidence >= 0.4:
                filtered.append(med)
            else:
                logger.warning(
                    f"Dropping likely-hallucinated medicine: {med.medicine_name} "
                    f"(model's own extraction_confidence={med.extraction_confidence:.2f}, "
                    f"no database corroboration)"
                )
        return filtered
    
    def _populate_urdu_summaries(self, medicines: List[MedicineDetail]) -> None:

        if not medicines:
            return
        
        summary_count = 0
        
        for med in medicines:
            # Process 'side_effects' independently
            if med.side_effects and med.side_effects != "unread" and med.side_effects.strip():
                logger.debug(f"Summarizing side_effects for {med.medicine_name}")
                summary = summarize_uses_precautions(
                    medicine_name=med.medicine_name,
                    text=med.side_effects,
                    field_type="side_effects"
                )
                if summary:
                    med.side_effects_urdu_short = summary
                    summary_count += 1
            
            # Process 'precautions' independently
            if med.precautions and med.precautions != "unread" and med.precautions.strip():
                logger.debug(f"Summarizing precautions for {med.medicine_name}")
                summary = summarize_uses_precautions(
                    medicine_name=med.medicine_name,
                    text=med.precautions,
                    field_type="precautions"
                )
                if summary:
                    med.precautions_urdu_short = summary
                    summary_count += 1
        
        logger.info(f"Generated {summary_count} Urdu summaries across {len(medicines)} medicine(s)")
    
    async def process_batch(
        self,
        image_paths: List[Union[str, Path]],
        skip_fallback: bool = False
    ) -> List[PrescriptionResponse]:

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

    pipeline = ParchaAIPipeline()
    return await pipeline.process_image(image_path)


async def process_prescription_sync_wrapper(image_path: Union[str, Path]) -> PrescriptionResponse:

    return await quick_process(image_path)