
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

        score = medicine.extraction_confidence * 0.55

        completeness_score = self._calculate_completeness(medicine)
        score += completeness_score * 0.20

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

        Parameters
        ----------
        medicine : MedicineDetail
            Medicine object
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
        
        logger.info("Merging primary and fallback results (recall-only, no overwrite)")

        if not fallback_medicines:
            logger.info("Fallback produced no medicines -- keeping primary as-is")
            final_medicines = self.scorer.flag_low_confidence_medicines(
                primary_medicines,
                fuzzy_scores_primary
            )
            self.fallback_called = True
            return final_medicines, False

        unmatched_fallback = []
        for fb_med in fallback_medicines:
            already_present = any(
                medicine_names_match(fb_med.medicine_name, primary_med.medicine_name)
                for primary_med in primary_medicines
            )
            if not already_present:
                unmatched_fallback.append(fb_med)

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