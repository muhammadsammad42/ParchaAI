"""
Confidence scoring and routing logic for ParchaAI.

This module calculates unified confidence scores and determines
whether to trigger fallback verification.

Confidence factors:
- Database match scores (RapidFuzz)
- Field completeness
- Database validation results
- Model consistency
"""

import logging
from typing import Dict, List, Optional, Tuple

from .validation import MedicineDetail
from .utils import medicine_names_match

logger = logging.getLogger(__name__)


class ConfidenceScorer:
    """
    Calculate confidence scores for extracted medicines.
    
    Attributes
    ----------
    threshold : float
        Confidence threshold for triggering fallback (default: 0.85)
    """
    
    def __init__(self, threshold: float = 0.85):
        """
        Initialize confidence scorer.
        
        Parameters
        ----------
        threshold : float, optional
            Confidence threshold for fallback routing, by default 0.85
        """
        self.threshold = threshold
        logger.info(f"ConfidenceScorer initialized (threshold: {self.threshold})")
    
    def calculate_medicine_confidence(
        self,
        medicine: MedicineDetail,
        fuzzy_score: Optional[float] = None
    ) -> float:
        """
        Calculate confidence score for a single medicine.

        Scoring factors (FIX -- see rationale below):
        - Model's own self-reported extraction confidence: 0.55 (the ONLY
          signal that actually reflects handwriting legibility)
        - Extracted-field completeness: 0.20 (of the 5 fields the extraction
          step actually controls: name/dosage/frequency/duration/purpose)
        - Database corroboration bonus: up to +0.25 (additive, NOT a
          prerequisite)

        RATIONALE FOR THE REWRITE
        --------------------------
        The previous formula spent 40% of the score on "found in local DB",
        30% on a fuzzy-match score that is simply absent (0) whenever no DB
        match clears the cutoff, and 30% on "field completeness" computed
        across all 10 fields -- including composition/uses/side_effects/
        precautions/manufacturer, which are *by design* always "unread"
        until a database match succeeds (see prompts.py: the extraction
        model is explicitly told to always write "unread" for these). That
        meant a real, clearly-written medicine that simply isn't in an
        11k-row reference CSV or in OpenFDA (extremely common for local-
        market brand names) was mathematically capped at ~0.0-0.15
        confidence no matter how legible the handwriting was -- exactly the
        0.03-0.15 scores observed in production logs, which then caused
        `_filter_medicines` to delete those (correctly-read) medicines
        outright as "hallucinations". This conflated "not in our database"
        with "probably wrong", which are not the same thing.

        The model is explicitly asked, per medicine, to self-report how
        confident it is based on handwriting legibility -- but that value
        was being discarded (hardcoded to 0.0) before it ever reached this
        function. It's now the dominant factor here, with database presence
        treated as a corroborating bonus rather than a near-total
        requirement.

        Parameters
        ----------
        medicine : MedicineDetail
            Medicine object to score
        fuzzy_score : float, optional
            RapidFuzz match score (0-100), if available

        Returns
        -------
        float
            Confidence score between 0.0 and 1.0
        """
        # Factor 1 (55%): the model's own self-reported confidence at
        # extraction time. This is the primary signal for "was this legible
        # handwriting", independent of whether a downstream database happens
        # to carry this particular brand.
        score = medicine.extraction_confidence * 0.55

        # Factor 2 (20%): completeness of the fields the extraction step
        # actually controls. Enrichment fields are intentionally excluded --
        # they measure database coverage, not extraction quality, and are
        # always "unread" pre-enrichment regardless of how well the image
        # was read.
        completeness_score = self._calculate_completeness(medicine)
        score += completeness_score * 0.20

        # Factor 3 (up to +0.25, additive): database corroboration. This
        # BOOSTS confidence when available rather than being a prerequisite
        # for a reasonable score -- absence of a DB match now costs at most
        # 0.25, not the ~0.70 it effectively cost before.
        db_bonus = 0.0
        if medicine.found_in_local_db:
            db_bonus += 0.15
        elif medicine.found_in_openfda:
            db_bonus += 0.10
        if fuzzy_score is not None:
            db_bonus += (fuzzy_score / 100.0) * 0.10
        score += min(db_bonus, 0.25)

        # Ensure score is within bounds
        score = max(0.0, min(1.0, score))

        logger.debug(
            f"Confidence for '{medicine.medicine_name}': {score:.3f} "
            f"(extraction_confidence: {medicine.extraction_confidence:.2f}, "
            f"db: {medicine.found_in_local_db}, fuzzy: {fuzzy_score}, "
            f"completeness: {completeness_score:.2f})"
        )

        return score
    
    def _calculate_completeness(self, medicine: MedicineDetail) -> float:
        """
        Calculate field completeness ratio.

        FIX: previously this counted all 10 fields, including the 5
        enrichment fields (composition/uses/side_effects/precautions/
        manufacturer) that are always "unread" until a database match
        succeeds -- see prompts.py, where the extraction model is
        explicitly instructed to always write "unread" for these. Counting
        them here meant this factor was really re-measuring database
        coverage a second time (on top of the DB-match factor), not
        extraction quality. Now only the 5 fields the vision model actually
        fills in from the image are counted.

        Parameters
        ----------
        medicine : MedicineDetail
            Medicine object
        
        Returns
        -------
        float
            Completeness ratio (0.0 to 1.0)
        """
        # Only the fields the extraction step itself is responsible for.
        fields = [
            medicine.medicine_name,
            medicine.dosage,
            medicine.frequency,
            medicine.duration,
            medicine.purpose,
        ]
        
        # Count non-empty and non-"unread" fields
        complete_count = 0
        for field in fields:
            if field and field.strip().lower() not in ['', 'unread', 'unknown', 'n/a']:
                complete_count += 1
        
        completeness = complete_count / len(fields)
        return completeness
    
    def calculate_prescription_confidence(
        self,
        medicines: List[MedicineDetail],
        fuzzy_scores: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Calculate overall prescription confidence (average of all medicines).
        
        Parameters
        ----------
        medicines : list of MedicineDetail
            All extracted medicines
        fuzzy_scores : dict, optional
            Mapping of medicine_name -> fuzzy_score
        
        Returns
        -------
        float
            Overall confidence score (0.0 to 1.0)
        """
        if not medicines:
            logger.warning("No medicines to score")
            return 0.0
        
        fuzzy_scores = fuzzy_scores or {}
        
        total_score = 0.0
        for medicine in medicines:
            fuzzy_score = fuzzy_scores.get(medicine.medicine_name)
            med_confidence = self.calculate_medicine_confidence(medicine, fuzzy_score)
            total_score += med_confidence
        
        avg_confidence = total_score / len(medicines)
        
        logger.info(
            f"Overall prescription confidence: {avg_confidence:.3f} "
            f"({len(medicines)} medicine(s))"
        )
        
        return avg_confidence
    
    def should_trigger_fallback(self, confidence: float) -> bool:
        """
        Determine if fallback verification should be triggered.
        
        Parameters
        ----------
        confidence : float
            Calculated confidence score
        
        Returns
        -------
        bool
            True if confidence is below threshold
        """
        trigger = confidence < self.threshold
        
        if trigger:
            logger.warning(
                f"Confidence {confidence:.3f} below threshold {self.threshold} - "
                f"triggering fallback"
            )
        else:
            logger.info(f"Confidence {confidence:.3f} above threshold - no fallback needed")
        
        return trigger
    
    def flag_low_confidence_medicines(
        self,
        medicines: List[MedicineDetail],
        fuzzy_scores: Optional[Dict[str, float]] = None
    ) -> List[MedicineDetail]:
        """
        Flag individual medicines with low confidence for human review.
        
        Parameters
        ----------
        medicines : list of MedicineDetail
            Medicines to evaluate
        fuzzy_scores : dict, optional
            Fuzzy match scores
        
        Returns
        -------
        list of MedicineDetail
            Updated medicines with flags set
        """
        fuzzy_scores = fuzzy_scores or {}
        
        for medicine in medicines:
            fuzzy_score = fuzzy_scores.get(medicine.medicine_name)
            med_confidence = self.calculate_medicine_confidence(medicine, fuzzy_score)
            
            # Update confidence field
            medicine.confidence = round(med_confidence, 3)
            
            # Flag if below threshold
            if med_confidence < self.threshold:
                medicine.low_confidence = True
                medicine.requires_human_review = True
                
                logger.warning(
                    f"Flagged '{medicine.medicine_name}' for review "
                    f"(confidence: {med_confidence:.3f})"
                )
        
        return medicines


class FallbackRouter:
    """
    Routes extraction to fallback model when confidence is low.
    
    This class implements the ONE verification pass rule:
    - If primary confidence < threshold, call fallback ONCE
    - Use fallback ONLY to add medicines primary genuinely missed (recall)
    - Never let fallback overwrite primary's own extracted field values
    """
    
    # FIX (qwen migration): minimum self-reported extraction_confidence a
    # fallback-only medicine must have before we add it to the final list.
    # Prevents a weaker fallback model's low-confidence guesses from
    # inflating the hallucination rate.
    MIN_FALLBACK_ADD_CONFIDENCE = 0.6

    def __init__(self, confidence_threshold: float = 0.85):
        """
        Initialize fallback router.
        
        Parameters
        ----------
        confidence_threshold : float, optional
            Confidence threshold for routing, by default 0.85
        """
        self.scorer = ConfidenceScorer(threshold=confidence_threshold)
        self.fallback_called = False
        logger.info("FallbackRouter initialized")
    
    def evaluate_and_route(
        self,
        medicines: List[MedicineDetail],
        fuzzy_scores: Optional[Dict[str, float]] = None
    ) -> Tuple[bool, float]:
        """
        Evaluate medicines and decide if fallback is needed.
        
        Parameters
        ----------
        medicines : list of MedicineDetail
            Primary extraction results
        fuzzy_scores : dict, optional
            Fuzzy match scores
        
        Returns
        -------
        tuple of (bool, float)
            (should_use_fallback, confidence_score)
        """
        confidence = self.scorer.calculate_prescription_confidence(
            medicines,
            fuzzy_scores
        )
        
        should_fallback = self.scorer.should_trigger_fallback(confidence)
        
        return should_fallback, confidence
    
    def merge_fallback_results(
        self,
        primary_medicines: List[MedicineDetail],
        fallback_medicines: List[MedicineDetail],
        fuzzy_scores_primary: Optional[Dict[str, float]] = None,
        fuzzy_scores_fallback: Optional[Dict[str, float]] = None
    ) -> Tuple[List[MedicineDetail], bool]:
        """
        Merge primary and fallback results -- RECALL-ONLY, never overwrite.

        FIX (qwen migration -- IMPORTANT):
        The previous version of this method compared primary vs. fallback
        wholesale on completeness/confidence and, if fallback "looked more
        complete", swapped in fallback's ENTIRE medicine list in place of
        primary's. That was tuned around llama-4-scout, which happened to
        produce fallback extractions roughly on par with (or better than)
        Gemini's primary pass.

        With the current fallback model (qwen/qwen3.6-27b), that same logic
        actively hurt accuracy: qwen fills in frequency/duration more often
        than it should (making its output look "more complete" by this
        metric) even when those fields are guesses rather than legible
        reads, and it is less disciplined about the "unread" convention.
        Since completeness doesn't measure correctness, the merge was
        handing wins to a worse-but-fuller-looking extraction -- which is
        exactly why frequency_accuracy, duration_accuracy, hallucination_rate,
        and average confidence all regressed together the moment the Groq
        parse error was fixed and this logic actually started firing.

        NEW STRATEGY: Gemini (primary) is the trusted extractor. Its
        per-medicine field values are NEVER overwritten by fallback. The
        fallback model is used strictly to catch RECALL misses: any
        fallback medicine that doesn't fuzzy-match anything already in
        primary is treated as a possible missed medicine and ADDED to the
        final list -- but only if the fallback model itself reported
        reasonable confidence in it (>= MIN_FALLBACK_ADD_CONFIDENCE),
        which keeps a low-confidence fallback guess from inflating the
        hallucination rate.

        Parameters
        ----------
        primary_medicines : list of MedicineDetail
            Primary extraction results
        fallback_medicines : list of MedicineDetail
            Fallback extraction results, already run through the same
            validation/enrichment pipeline as the primary results (i.e.
            local DB + OpenFDA lookups already applied)
        fuzzy_scores_primary : dict, optional
            Fuzzy scores for primary
        fuzzy_scores_fallback : dict, optional
            Fuzzy scores for fallback

        Returns
        -------
        tuple of (list, bool)
            (final_medicines, fallback_contributed) -- the second value is
            True only if fallback actually added a medicine primary missed.
        """
        logger.info("Merging primary and fallback results (recall-only, no overwrite)")

        if not fallback_medicines:
            logger.info("Fallback produced no medicines -- keeping primary as-is")
            final_medicines = self.scorer.flag_low_confidence_medicines(
                primary_medicines,
                fuzzy_scores_primary
            )
            self.fallback_called = True
            return final_medicines, False

        # Identify fallback medicines that do NOT correspond to anything
        # already present in primary (by fuzzy medicine-name match, same
        # matcher the evaluator uses for ground-truth comparison).
        unmatched_fallback = []
        for fb_med in fallback_medicines:
            already_present = any(
                medicine_names_match(fb_med.medicine_name, primary_med.medicine_name)
                for primary_med in primary_medicines
            )
            if not already_present:
                unmatched_fallback.append(fb_med)

        # Of those, only add ones the fallback model itself was reasonably
        # confident about -- an unmatched medicine the model itself flagged
        # as low-confidence is exactly the kind of guess that inflates
        # hallucination_rate without a real recall benefit.
        added = [
            m for m in unmatched_fallback
            if m.extraction_confidence >= self.MIN_FALLBACK_ADD_CONFIDENCE
        ]

        if added:
            logger.info(
                f"Fallback found {len(added)} medicine(s) missed by primary "
                f"(extraction_confidence >= {self.MIN_FALLBACK_ADD_CONFIDENCE}): "
                f"{[m.medicine_name for m in added]}"
            )
        skipped = len(unmatched_fallback) - len(added)
        if skipped:
            logger.info(
                f"Discarded {skipped} unmatched fallback medicine(s) below "
                f"the add-confidence floor (likely low-confidence guesses)"
            )

        final_medicines = list(primary_medicines) + added

        merged_fuzzy_scores = dict(fuzzy_scores_primary or {})
        merged_fuzzy_scores.update(fuzzy_scores_fallback or {})

        final_medicines = self.scorer.flag_low_confidence_medicines(
            final_medicines,
            merged_fuzzy_scores
        )

        self.fallback_called = True
        fallback_contributed = len(added) > 0
        return final_medicines, fallback_contributed
    
    def _estimate_completeness_from_dicts(
        self,
        medicine_dicts: List[Dict]
    ) -> float:
        """
        Estimate completeness from raw medicine dictionaries.

        Retained for any external/legacy callers; no longer used internally
        by merge_fallback_results (see docstring there for why).

        Parameters
        ----------
        medicine_dicts : list of dict
            Raw medicine data
        
        Returns
        -------
        float
            Estimated completeness ratio
        """
        if not medicine_dicts:
            return 0.0
        
        total_completeness = 0.0
        
        for med_dict in medicine_dicts:
            fields = [
                med_dict.get('medicine_name', ''),
                med_dict.get('dosage', ''),
                med_dict.get('frequency', ''),
                med_dict.get('duration', ''),
                med_dict.get('purpose', ''),
                med_dict.get('composition', ''),
                med_dict.get('uses', ''),
                med_dict.get('side_effects', ''),
                med_dict.get('precautions', ''),
                med_dict.get('manufacturer', '')
            ]
            
            complete_count = sum(
                1 for f in fields
                if f and f.strip().lower() not in ['', 'unread', 'unknown', 'n/a']
            )
            
            total_completeness += complete_count / len(fields)
        
        return total_completeness / len(medicine_dicts)
    
    def finalize_medicines(
        self,
        medicines: List[MedicineDetail],
        fuzzy_scores: Optional[Dict[str, float]] = None
    ) -> List[MedicineDetail]:
        """
        Final pass to ensure all confidence scores and flags are set.
        
        Parameters
        ----------
        medicines : list of MedicineDetail
            Medicines to finalize
        fuzzy_scores : dict, optional
            Fuzzy match scores
        
        Returns
        -------
        list of MedicineDetail
            Finalized medicines
        """
        return self.scorer.flag_low_confidence_medicines(medicines, fuzzy_scores)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def calculate_confidence(
    medicines: List[MedicineDetail],
    fuzzy_scores: Optional[Dict[str, float]] = None,
    threshold: float = 0.85
) -> Tuple[float, bool]:
    """
    Quick confidence calculation and fallback decision.
    
    Parameters
    ----------
    medicines : list of MedicineDetail
        Extracted medicines
    fuzzy_scores : dict, optional
        Fuzzy match scores
    threshold : float, optional
        Confidence threshold, by default 0.85
    
    Returns
    -------
    tuple of (float, bool)
        (confidence_score, should_trigger_fallback)
    
    Examples
    --------
    >>> confidence, trigger = calculate_confidence(medicines, fuzzy_scores)
    >>> if trigger:
    ...     print(f"Low confidence ({confidence:.2f}) - fallback needed")
    """
    scorer = ConfidenceScorer(threshold=threshold)
    confidence = scorer.calculate_prescription_confidence(medicines, fuzzy_scores)
    should_fallback = scorer.should_trigger_fallback(confidence)
    return confidence, should_fallback


def update_medicine_confidences(
    medicines: List[MedicineDetail],
    fuzzy_scores: Optional[Dict[str, float]] = None
) -> List[MedicineDetail]:
    """
    Update confidence scores and flags for all medicines.
    
    Parameters
    ----------
    medicines : list of MedicineDetail
        Medicines to update
    fuzzy_scores : dict, optional
        Fuzzy match scores
    
    Returns
    -------
    list of MedicineDetail
        Updated medicines
    """
    scorer = ConfidenceScorer()
    return scorer.flag_low_confidence_medicines(medicines, fuzzy_scores)