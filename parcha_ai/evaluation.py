"""
Evaluation and benchmarking suite for ParchaAI.

This module runs the complete pipeline against the ground truth dataset
and calculates comprehensive metrics.

Metrics calculated:
- Medicine Name Accuracy
- Dosage Accuracy
- Frequency Accuracy
- Duration Accuracy
- Purpose Accuracy
- Precision, Recall, F1 Score
- Exact Match Accuracy
- Hallucination Rate
- Average Inference Time
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from scipy.optimize import linear_sum_assignment

from .utils import (
    normalize_field,
    normalize_text,
    dosages_match,
    medicine_names_match,
    strip_form_words,
)

from .config import get_config
from .pipeline import ParchaAIPipeline
from .validation import PrescriptionResponse

logger = logging.getLogger(__name__)

# Weights for clinical_weighted_accuracy. medicine_name and dosage are
# weighted higher than frequency/duration because those two are where an
# extraction error translates directly into patient harm (wrong drug, wrong
# strength). Adjust if your clinical advisor/mentor wants a different split
# -- these are a defensible starting point, not a fixed standard.
CLINICAL_WEIGHTS = {
    'medicine_name': 0.35,
    'dosage': 0.35,
    'frequency': 0.15,
    'duration': 0.15,
}


class EvaluationMetrics:
    """Container for evaluation metrics."""
    
    def __init__(self):
        """Initialize metric counters."""
        self.total_predictions = 0
        self.total_ground_truth = 0
        
        self.medicine_name_correct = 0
        self.dosage_correct = 0
        self.frequency_correct = 0
        self.duration_correct = 0
        self.purpose_correct = 0
        self.purpose_gradable = 0
        
        self.exact_matches = 0
        self.hallucinations = 0
        self.false_negatives = 0

        # Confidence-calibration / safety-net tracking. A prediction is
        # "clinically correct" here if its medicine_name AND dosage both
        # match ground truth (the two fields where an error can directly
        # cause patient harm). This is tracked separately from field
        # accuracy so we can answer: "when the pipeline is wrong, does it
        # know it, and does it flag it for a human?"
        self.correct_confidence_sum = 0.0
        self.correct_count = 0
        self.incorrect_confidence_sum = 0.0
        self.incorrect_count = 0
        self.incorrect_flagged_count = 0  # incorrect AND low_confidence/requires_human_review

        self.total_inference_time = 0.0
        
        self.per_image_results = []
        # Raw predicted-vs-truth field values for every matched pair,
        # hallucination, and missed ground-truth entry across all images --
        # exported separately so real failures can be inspected instead of
        # guessed at from aggregate accuracy numbers.
        self.debug_rows = []
    
    def calculate_aggregates(self) -> Dict:
        """
        Calculate aggregate metrics.
        
        Returns
        -------
        dict
            Dictionary of calculated metrics
        """
        # Avoid division by zero
        n_pred = max(self.total_predictions, 1)
        n_truth = max(self.total_ground_truth, 1)
        n_images = max(len(self.per_image_results), 1)
        
        # Field accuracies
        medicine_name_accuracy = (self.medicine_name_correct / n_pred) * 100
        dosage_accuracy = (self.dosage_correct / n_pred) * 100
        frequency_accuracy = (self.frequency_correct / n_pred) * 100
        duration_accuracy = (self.duration_correct / n_pred) * 100

        
        # Precision, Recall, F1
        # True Positives: correctly extracted medicines
        # False Positives: hallucinated medicines
        # False Negatives: missed medicines
        
        true_positives = self.medicine_name_correct
        false_positives = self.hallucinations
        false_negatives = self.false_negatives
        
        precision = (
            (true_positives / (true_positives + false_positives)) * 100
            if (true_positives + false_positives) > 0
            else 0.0
        )
        
        recall = (
            (true_positives / (true_positives + false_negatives)) * 100
            if (true_positives + false_negatives) > 0
            else 0.0
        )
        
        f1_score = (
            (2 * precision * recall) / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )
        
        # Exact match accuracy
        exact_match_accuracy = (self.exact_matches / n_pred) * 100
        
        # Hallucination rate
        hallucination_rate = (self.hallucinations / n_pred) * 100
        
        # Average inference time
        avg_inference_time = self.total_inference_time / n_images

        # --- Composite accuracy metrics ---
        # Macro Field Accuracy: simple average of the 4 extractable fields
        # that actually have ground truth. This is the standard way
        # document/entity-extraction systems report a single "accuracy"
        # number (analogous to macro-F1 across fields) -- it doesn't hide
        # weak fields the way an unweighted micro-average over all
        # predicted tokens could.
        macro_field_accuracy = round(
            (medicine_name_accuracy + dosage_accuracy + frequency_accuracy + duration_accuracy) / 4,
            2
        )

        # Clinical-Weighted Accuracy: medicine_name and dosage are weighted
        # higher than frequency/duration because getting the WRONG DRUG or
        # WRONG DOSE is a direct patient-safety failure, whereas a
        # frequency/duration miss is typically caught by the pharmacist or
        # is lower-stakes. Weights are a judgment call for your domain --
        # adjust CLINICAL_WEIGHTS below if you disagree with this split.
        clinical_weighted_accuracy = round(
            medicine_name_accuracy * CLINICAL_WEIGHTS['medicine_name']
            + dosage_accuracy * CLINICAL_WEIGHTS['dosage']
            + frequency_accuracy * CLINICAL_WEIGHTS['frequency']
            + duration_accuracy * CLINICAL_WEIGHTS['duration'],
            2
        )

        # --- Safety-net / confidence-calibration metrics ---
        # These answer a different question than "is the extraction
        # right" -- they answer "when the pipeline IS wrong, does the
        # confidence score / human-review flag actually catch it?" This
        # matters more for a medical safety project than raw accuracy
        # alone, since a wrong-but-unflagged extraction is the actual
        # patient-harm scenario.
        avg_confidence_correct = (
            round(self.correct_confidence_sum / self.correct_count, 3)
            if self.correct_count > 0 else None
        )
        avg_confidence_incorrect = (
            round(self.incorrect_confidence_sum / self.incorrect_count, 3)
            if self.incorrect_count > 0 else None
        )
        # Of everything the pipeline got wrong (wrong drug or wrong dose,
        # or a hallucinated medicine), what fraction did it flag as
        # low-confidence / needing human review?
        human_review_catch_rate = (
            round((self.incorrect_flagged_count / self.incorrect_count) * 100, 2)
            if self.incorrect_count > 0 else None
        )
        # The inverse and more important number for a safety writeup: how
        # often is the pipeline confidently wrong with no safety net?
        false_reassurance_rate = (
            round(100 - human_review_catch_rate, 2)
            if human_review_catch_rate is not None else None
        )

        return {
            'total_images': n_images,
            'total_predictions': self.total_predictions,
            'total_ground_truth': self.total_ground_truth,
            'medicine_name_accuracy': round(medicine_name_accuracy, 2),
            'dosage_accuracy': round(dosage_accuracy, 2),
            'frequency_accuracy': round(frequency_accuracy, 2),
            'duration_accuracy': round(duration_accuracy, 2),
            'precision': round(precision, 2),
            'recall': round(recall, 2),
            'f1_score': round(f1_score, 2),
            'exact_match_accuracy': round(exact_match_accuracy, 2),
            'hallucination_rate': round(hallucination_rate, 2),
            'average_inference_time': round(avg_inference_time, 3),

            # --- Composite headline metrics ---
            'macro_field_accuracy': macro_field_accuracy,
            'clinical_weighted_accuracy': clinical_weighted_accuracy,

            # --- Safety-net / confidence calibration ---
            'avg_confidence_when_correct': avg_confidence_correct,
            'avg_confidence_when_incorrect': avg_confidence_incorrect,
            'human_review_catch_rate': human_review_catch_rate,
            'false_reassurance_rate': false_reassurance_rate,
        }


class PrescriptionEvaluator:
    """
    Evaluates prescription extraction against ground truth.
    
    Attributes
    ----------
    pipeline : ParchaAIPipeline
        Extraction pipeline
    ground_truth_path : Path
        Path to ground truth CSV
    images_dir : Path
        Directory containing prescription images
    outputs_dir : Path
        Directory for evaluation outputs
    """
    
    def __init__(
        self,
        ground_truth_path: Optional[Path] = None,
        images_dir: Optional[Path] = None,
        outputs_dir: Optional[Path] = None
    ):
        """
        Initialize evaluator.
        
        Parameters
        ----------
        ground_truth_path : Path, optional
            Path to ground truth CSV
        images_dir : Path, optional
            Path to images directory
        outputs_dir : Path, optional
            Path to outputs directory
        """
        config = get_config()
        
        self.pipeline = ParchaAIPipeline()
        
        # Set paths
        self.ground_truth_path = ground_truth_path or config.ground_truth_csv
        
        self.images_dir = images_dir or config.raw_images_dir
        
        self.outputs_dir = outputs_dir or config.outputs_dir
        self.outputs_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Evaluator initialized")
        logger.info(f"  Ground truth: {self.ground_truth_path}")
        logger.info(f"  Images: {self.images_dir}")
        logger.info(f"  Outputs: {self.outputs_dir}")
    
    def load_ground_truth(self) -> pd.DataFrame:
        """
        Load ground truth CSV.
        
        Returns
        -------
        pd.DataFrame
            Ground truth data
        
        Raises
        ------
        FileNotFoundError
            If ground truth file not found
        """
        if not self.ground_truth_path.exists():
            raise FileNotFoundError(f"Ground truth not found: {self.ground_truth_path}")
        
        # utf-8-sig strips a leading BOM character if present, which otherwise
        # corrupts the first column name (e.g. 'image_path' becomes
        # '\ufeffimage_path') and breaks every column lookup against it.
        df = pd.read_csv(self.ground_truth_path, encoding='utf-8-sig')
        df.columns = [c.strip() for c in df.columns]
        
        logger.info(f"Loaded ground truth: {len(df)} entries")
        return df
    
    def get_image_paths(self) -> List[Path]:
        """
        Get all prescription image paths.
        
        Returns
        -------
        list of Path
            List of image file paths
        """
        if not self.images_dir.exists():
            raise FileNotFoundError(f"Images directory not found: {self.images_dir}")
        
        # Get all jpg images
        image_paths = sorted(self.images_dir.glob('*.jpg'))
        
        logger.info(f"Found {len(image_paths)} prescription images")
        return image_paths
    
    def compare_medicine(
        self,
        predicted: Dict,
        ground_truth: Dict
    ) -> Dict[str, bool]:
        """
        Compare a single predicted medicine against ground truth.
        
        CRITICAL: Normalizes both sides before comparison.
        
        Parameters
        ----------
        predicted : dict
            Predicted medicine fields
        ground_truth : dict
            Ground truth medicine fields
        
        Returns
        -------
        dict
            Dictionary of field-level match results
        """
        # Normalize both sides (basic whitespace/null cleanup only -- the
        # field-specific matchers below handle deeper semantic normalization)
        pred_name_raw = normalize_text(predicted.get('medicine_name', ''))
        pred_dosage_raw = normalize_text(predicted.get('dosage', ''))
        pred_frequency = normalize_text(predicted.get('frequency', ''))
        pred_duration = normalize_text(predicted.get('duration', ''))
        pred_purpose = normalize_text(predicted.get('purpose', ''))

        truth_name_raw = normalize_text(ground_truth.get('medicine_name', ''))
        truth_dosage_raw = normalize_text(ground_truth.get('dosage', ''))
        truth_frequency = normalize_text(ground_truth.get('frequency', ''))
        truth_duration = normalize_text(ground_truth.get('duration', ''))
        truth_purpose = normalize_text(ground_truth.get('purpose', ''))

        pred_frequency_norm = normalize_field('frequency', pred_frequency)
        truth_frequency_norm = normalize_field('frequency', truth_frequency)
        pred_duration_norm = normalize_field('duration', pred_duration)
        truth_duration_norm = normalize_field('duration', truth_duration)

        # --- Medicine name: semantic match, not literal string equality ---
        # Ground truth often includes dosage-form/route words (e.g. "Syr X",
        # "X Ear Drops") that the extraction prompt deliberately tells the
        # model to omit. medicine_names_match() strips those words on both
        # sides and falls back to fuzzy token-set similarity, so "Megacv
        # Forte" and "Syr Megacv Forte" are correctly treated as the same
        # medicine instead of being marked wrong purely due to formatting.
        name_match = medicine_names_match(pred_name_raw, truth_name_raw)

        # --- Dosage: match on core strength + fuzzy, not literal equality ---
        # Ground truth dosage strings frequently carry extra administration
        # notes ("(take 1 tab)", "Day 1: 15 mL, Day 2: 7.5 mL") that the
        # model was explicitly told not to reproduce. dosages_match() strips
        # spacing/punctuation differences and compares the core
        # "<number> <unit>" strength so equivalent doses aren't penalized
        # for differing verbosity.
        dosage_match = dosages_match(pred_dosage_raw, truth_dosage_raw)

        results = {
            'medicine_name_match': name_match,
            'dosage_match': dosage_match,
            'frequency_match': pred_frequency_norm.lower() == truth_frequency_norm.lower(),
            'duration_match': pred_duration_norm.lower() == truth_duration_norm.lower(),
            'purpose_match': pred_purpose.lower() == truth_purpose.lower(),
        }

        if not results['frequency_match'] and pred_frequency_norm != 'unread' and truth_frequency_norm != 'unread':
            frequency_tokens = set(pred_frequency_norm.lower().split())
            truth_tokens = set(truth_frequency_norm.lower().split())
            frequency_overlap = len(frequency_tokens & truth_tokens) / max(1, len(frequency_tokens | truth_tokens))
            results['frequency_match'] = frequency_overlap >= 0.5
            # Jaccard overlap penalizes short phrases unfairly (e.g. "at
            # bedtime" vs "bedtime" is only 50%). Fuzzy token-set ratio
            # catches these near-identical phrasings the same way
            # dosage/medicine_name matching already does elsewhere.
            if not results['frequency_match']:
                results['frequency_match'] = fuzz.token_set_ratio(
                    pred_frequency_norm.lower(), truth_frequency_norm.lower()
                ) >= 85

        if not results['duration_match'] and pred_duration_norm != 'unread' and truth_duration_norm != 'unread':
            duration_tokens = set(pred_duration_norm.lower().split())
            truth_tokens = set(truth_duration_norm.lower().split())
            duration_overlap = len(duration_tokens & truth_tokens) / max(1, len(duration_tokens | truth_tokens))
            results['duration_match'] = duration_overlap >= 0.5
            if not results['duration_match']:
                results['duration_match'] = fuzz.token_set_ratio(
                    pred_duration_norm.lower(), truth_duration_norm.lower()
                ) >= 85

       
        if truth_purpose == 'unread':
            results['purpose_has_ground_truth'] = False
        else:
            results['purpose_has_ground_truth'] = True
            if not results['purpose_match']:
                # NOTE: previously did a local "from rapidfuzz import fuzz"
                # here. Python treats any name assigned ANYWHERE in a
                # function as local to the whole function, so that local
                # import silently shadowed the module-level `fuzz` import
                # used earlier in this same function (frequency/duration
                # fuzzy fallback) -- causing UnboundLocalError there. `fuzz`
                # is already imported at module level, so just use it.
                results['purpose_match'] = fuzz.token_set_ratio(
                    pred_purpose.lower(), truth_purpose.lower()
                ) >= 80

        # Exact match: core identifying/dosing fields only. Purpose is
        # excluded since ground truth doesn't actually contain it (see above).
        results['exact_match'] = all([
            results['medicine_name_match'],
            results['dosage_match'],
            results['frequency_match'],
            results['duration_match'],
        ])

        return results
    
    def _compute_name_similarity(
        self,
        predicted: Dict,
        ground_truth: Dict
    ) -> float:
        """
        Compute fuzzy similarity between normalized medicine names.

        Parameters
        ----------
        predicted : dict
            Predicted medicine dictionary
        ground_truth : dict
            Ground-truth medicine dictionary

        Returns
        -------
        float
            Similarity score in the range [0, 100]
        """
        # Strip dosage-form/route words (e.g. "Syr", "Ear Drops") before
        # comparing -- ground truth carries them, the extraction prompt
        # deliberately tells the model not to. Without this, a correctly
        # identified medicine like "Megacv Forte" vs truth "Syr Megacv Forte"
        # scores artificially low and gets treated as an unmatched
        # prediction (i.e. counted as a hallucination) purely due to
        # formatting, not because the medicine was actually wrong.
        pred_name = strip_form_words(normalize_text(predicted.get('medicine_name', '')))
        truth_name = strip_form_words(normalize_text(ground_truth.get('medicine_name', '')))

        if not pred_name and not truth_name:
            return 100.0
        if not pred_name or not truth_name:
            return 0.0

        # token_set_ratio (not token_sort_ratio) so that extra tokens
        # present on only one side don't drag the score down.
        return float(fuzz.token_set_ratio(pred_name, truth_name))

    def _build_assignment_pairs(
        self,
        predicted_medicines: List[Dict],
        ground_truth_rows: List[Dict]
    ) -> List[Tuple[int, int]]:
        """
        Build optimal one-to-one matches between predictions and ground truth.

        The matching is solved with the Hungarian algorithm over a cost matrix
        built from fuzzy medicine-name similarity. Pairs below an empirical
        threshold are treated as unmatched and left for false-positive / false-
        negative accounting.

        Parameters
        ----------
        predicted_medicines : list of dict
            Predicted medicines for the image
        ground_truth_rows : list of dict
            Ground-truth medicines for the image

        Returns
        -------
        list of tuple[int, int]
            Accepted matched pairs as (prediction_index, ground_truth_index)
        """
        n_predicted = len(predicted_medicines)
        n_truth = len(ground_truth_rows)

        if n_predicted == 0 or n_truth == 0:
            return []

        matching_penalty = 10000.0
        # Lowered from 75 -> 70: now that names are compared with form-words
        # stripped and token_set_ratio, genuine matches already score close
        # to 100, so this only needs to catch real near-misses (minor OCR
        # errors), not compensate for formatting differences anymore.
        matching_threshold = 70.0
        cost_matrix = np.full((n_predicted, n_truth), matching_penalty, dtype=float)

        for pred_idx, pred_med in enumerate(predicted_medicines):
            for truth_idx, truth_med in enumerate(ground_truth_rows):
                similarity = self._compute_name_similarity(pred_med, truth_med)
                if similarity >= matching_threshold:
                    cost_matrix[pred_idx, truth_idx] = -similarity
                else:
                    cost_matrix[pred_idx, truth_idx] = matching_penalty

        row_indices, col_indices = linear_sum_assignment(cost_matrix)

        matched_pairs: List[Tuple[int, int]] = []
        for pred_idx, truth_idx in zip(row_indices, col_indices):
            similarity = self._compute_name_similarity(
                predicted_medicines[pred_idx],
                ground_truth_rows[truth_idx]
            )
            if similarity >= matching_threshold:
                matched_pairs.append((pred_idx, truth_idx))

        return matched_pairs

    def evaluate_single_image(
        self,
        prediction: PrescriptionResponse,
        ground_truth_rows: List[Dict],
        image_filename: Optional[str] = None
    ) -> Dict:
        """
        Evaluate a single image prediction against ground truth.

        Predictions and ground-truth medicines are first aligned with an
        optimal assignment based on fuzzy medicine-name similarity. Only after
        this pairing is established are field-level comparisons executed for the
        matched pairs.

        Parameters
        ----------
        prediction : PrescriptionResponse
            Pipeline prediction
        ground_truth_rows : list of dict
            Ground truth medicines for this image

        Returns
        -------
        dict
            Per-image evaluation results
        """
        predicted_medicines = [
            med.model_dump() for med in prediction.extracted_medicines
        ]

        n_predicted = len(predicted_medicines)
        n_truth = len(ground_truth_rows)

        results = {
            'image_filename': image_filename or (
                Path(prediction.image_path).name if prediction.image_path
                else prediction.prescription_id
            ),
            'n_predicted': n_predicted,
            'n_truth': n_truth,
            'medicine_name_correct': 0,
            'dosage_correct': 0,
            'frequency_correct': 0,
            'duration_correct': 0,
            'purpose_correct': 0,
            'purpose_gradable': 0,  # pairs where ground truth actually had a purpose value
            'exact_matches': 0,
            'hallucinations': 0,
            'false_negatives': 0,
            'processing_time': prediction.extraction_time_seconds or 0.0,
            'used_fallback': prediction.fallback_model_used,

            # Safety-net tracking (see EvaluationMetrics for definitions)
            'correct_confidence_sum': 0.0,
            'correct_count': 0,
            'incorrect_confidence_sum': 0.0,
            'incorrect_count': 0,
            'incorrect_flagged_count': 0,

            # Raw predicted-vs-truth strings for every matched pair, plus
            # every hallucination/false-negative, so failures can actually
            # be inspected instead of guessed at from aggregate counts.
            'debug_rows': [],
        }

        matched_pairs = self._build_assignment_pairs(
            predicted_medicines,
            ground_truth_rows
        )
        matched_pred_indices = {pred_idx for pred_idx, _ in matched_pairs}
        matched_truth_indices = {truth_idx for _, truth_idx in matched_pairs}

        for pred_idx, truth_idx in matched_pairs:
            pred_med = predicted_medicines[pred_idx]
            truth_med = ground_truth_rows[truth_idx]
            comparison = self.compare_medicine(pred_med, truth_med)

            results['debug_rows'].append({
                'image_filename': results['image_filename'],
                'row_type': 'matched',
                'pred_medicine_name': pred_med.get('medicine_name', ''),
                'truth_medicine_name': truth_med.get('medicine_name', ''),
                'medicine_name_match': comparison['medicine_name_match'],
                'pred_dosage': pred_med.get('dosage', ''),
                'truth_dosage': truth_med.get('dosage', ''),
                'dosage_match': comparison['dosage_match'],
                'pred_frequency': pred_med.get('frequency', ''),
                'truth_frequency': truth_med.get('frequency', ''),
                'frequency_match': comparison['frequency_match'],
                'pred_duration': pred_med.get('duration', ''),
                'truth_duration': truth_med.get('duration', ''),
                'duration_match': comparison['duration_match'],
                'confidence': pred_med.get('confidence', ''),
            })

            if comparison['medicine_name_match']:
                results['medicine_name_correct'] += 1
            if comparison['dosage_match']:
                results['dosage_correct'] += 1
            if comparison['frequency_match']:
                results['frequency_correct'] += 1
            if comparison['duration_match']:
                results['duration_correct'] += 1
            if comparison['purpose_has_ground_truth']:
                results['purpose_gradable'] += 1
                if comparison['purpose_match']:
                    results['purpose_correct'] += 1
            if comparison['exact_match']:
                results['exact_matches'] += 1

            # Clinically correct = right drug AND right dose. This is the
            # bar used for the confidence-calibration / human-review
            # safety-net metrics -- deliberately stricter than "matched",
            # since a matched-but-wrong-dose prediction is still a safety
            # risk that should be caught by the confidence flag.
            is_clinically_correct = comparison['medicine_name_match'] and comparison['dosage_match']
            confidence = float(pred_med.get('confidence', 0.0) or 0.0)
            flagged = bool(pred_med.get('low_confidence') or pred_med.get('requires_human_review'))

            if is_clinically_correct:
                results['correct_confidence_sum'] += confidence
                results['correct_count'] += 1
            else:
                results['incorrect_confidence_sum'] += confidence
                results['incorrect_count'] += 1
                if flagged:
                    results['incorrect_flagged_count'] += 1

        # Predictions that never matched anything in ground truth
        # (hallucinations) are unambiguously incorrect -- include them in
        # the safety-net accounting too, since a hallucinated medicine that
        # ISN'T flagged for review is the worst-case failure mode.
        for pred_idx, pred_med in enumerate(predicted_medicines):
            if pred_idx in matched_pred_indices:
                continue
            confidence = float(pred_med.get('confidence', 0.0) or 0.0)
            flagged = bool(pred_med.get('low_confidence') or pred_med.get('requires_human_review'))
            results['incorrect_confidence_sum'] += confidence
            results['incorrect_count'] += 1
            if flagged:
                results['incorrect_flagged_count'] += 1
            results['debug_rows'].append({
                'image_filename': results['image_filename'],
                'row_type': 'hallucination',
                'pred_medicine_name': pred_med.get('medicine_name', ''),
                'truth_medicine_name': '',
                'medicine_name_match': False,
                'pred_dosage': pred_med.get('dosage', ''),
                'truth_dosage': '',
                'dosage_match': False,
                'pred_frequency': pred_med.get('frequency', ''),
                'truth_frequency': '',
                'frequency_match': False,
                'pred_duration': pred_med.get('duration', ''),
                'truth_duration': '',
                'duration_match': False,
                'confidence': confidence,
            })

        # Ground-truth medicines that never got matched to any prediction
        # (false negatives / missed medicines) -- capture these too, since
        # a missed medicine and a hallucinated one look identical in the
        # aggregate counts but need opposite fixes.
        for truth_idx, truth_med in enumerate(ground_truth_rows):
            if truth_idx in matched_truth_indices:
                continue
            results['debug_rows'].append({
                'image_filename': results['image_filename'],
                'row_type': 'missed_ground_truth',
                'pred_medicine_name': '',
                'truth_medicine_name': truth_med.get('medicine_name', ''),
                'medicine_name_match': False,
                'pred_dosage': '',
                'truth_dosage': truth_med.get('dosage', ''),
                'dosage_match': False,
                'pred_frequency': '',
                'truth_frequency': truth_med.get('frequency', ''),
                'frequency_match': False,
                'pred_duration': '',
                'truth_duration': truth_med.get('duration', ''),
                'duration_match': False,
                'confidence': '',
            })

        results['hallucinations'] = n_predicted - len(matched_pairs)
        results['false_negatives'] = n_truth - len(matched_pairs)

        return results
    
    async def run_evaluation(
        self,
        skip_fallback: bool = False,
        limit: Optional[int] = None
    ) -> Tuple[EvaluationMetrics, pd.DataFrame]:
        """
        Run complete evaluation on all images.
        
        Parameters
        ----------
        skip_fallback : bool, optional
            Skip fallback verification for faster evaluation, by default False
        limit : int, optional
            Limit number of images to evaluate (for testing), by default None
        
        Returns
        -------
        tuple of (EvaluationMetrics, pd.DataFrame)
            Aggregate metrics and per-image results DataFrame
        """
        logger.info("="*70)
        logger.info("STARTING EVALUATION")
        logger.info("="*70)
        
        # Load ground truth
        ground_truth_df = self.load_ground_truth()
        
        # Get image paths
        image_paths = self.get_image_paths()
        
        if limit:
            image_paths = image_paths[:limit]
            logger.info(f"Limiting evaluation to {limit} images")
        
        # Initialize metrics
        metrics = EvaluationMetrics()
        
        # Process each image
        for idx, image_path in enumerate(image_paths, 1):
            logger.info(f"\n[{idx}/{len(image_paths)}] Evaluating: {image_path.name}")
            
            try:
                # Run pipeline
                prediction = await self.pipeline.process_image(
                    image_path,
                    skip_fallback=skip_fallback
                )
                
                # Get corresponding ground truth
                image_key = image_path.stem  # e.g., "rx_01"
                truth_rows = ground_truth_df[
                    ground_truth_df['image_path'] == image_path.name
                ].to_dict('records')
                
                if not truth_rows:
                    logger.warning(f"No ground truth found for {image_path.name}")
                    continue
                
                # Evaluate
                image_results = self.evaluate_single_image(
                    prediction, truth_rows, image_filename=image_path.name
                )
                
                # Update metrics
                metrics.total_predictions += image_results['n_predicted']
                metrics.total_ground_truth += image_results['n_truth']
                metrics.medicine_name_correct += image_results['medicine_name_correct']
                metrics.dosage_correct += image_results['dosage_correct']
                metrics.frequency_correct += image_results['frequency_correct']
                metrics.duration_correct += image_results['duration_correct']
                metrics.purpose_correct += image_results['purpose_correct']
                metrics.purpose_gradable += image_results['purpose_gradable']
                metrics.correct_confidence_sum += image_results['correct_confidence_sum']
                metrics.correct_count += image_results['correct_count']
                metrics.incorrect_confidence_sum += image_results['incorrect_confidence_sum']
                metrics.incorrect_count += image_results['incorrect_count']
                metrics.incorrect_flagged_count += image_results['incorrect_flagged_count']
                metrics.exact_matches += image_results['exact_matches']
                metrics.hallucinations += image_results['hallucinations']
                metrics.false_negatives += image_results['false_negatives']
                metrics.total_inference_time += image_results['processing_time']

                # Pull debug rows out into their own collection -- they
                # don't belong in the per-image summary CSV (variable-length
                # list per row), and are exported separately.
                metrics.debug_rows.extend(image_results.pop('debug_rows', []))

                metrics.per_image_results.append(image_results)
                
                logger.info(
                    f"  Result: {image_results['medicine_name_correct']}/{image_results['n_truth']} "
                    f"correct names, {image_results['exact_matches']} exact matches"
                )
            
            except Exception as e:
                # NOTE: previously, any failure here (e.g. a Groq 429 rate
                # limit) silently dropped the image from the whole
                # evaluation, which is why only 18/27 images were scored
                # last run. _call_groq_vision() in extraction.py now retries
                # rate-limit errors with backoff before ever raising, so
                # this branch should only fire for genuine, non-recoverable
                # failures -- but it's logged loudly either way so it can't
                # go unnoticed again.
                logger.error(
                    f"SKIPPING {image_path.name} -- this will reduce total_images "
                    f"below the full dataset size. Reason: {e}",
                    exc_info=True
                )
                continue

            # Small pacing delay between images to stay well under Groq's
            # free-tier rate limit, independent of the per-call retry logic.
            await asyncio.sleep(get_config().inter_request_delay_seconds)
        
        # Convert per-image results to DataFrame
        results_df = pd.DataFrame(metrics.per_image_results)
        
        logger.info("\n" + "="*70)
        logger.info("EVALUATION COMPLETE")
        logger.info("="*70)
        
        return metrics, results_df
    
    def export_results(
        self,
        metrics: EvaluationMetrics,
        results_df: pd.DataFrame
    ) -> Tuple[Path, Path]:
        """
        Export evaluation results to CSV and JSON.
        
        Parameters
        ----------
        metrics : EvaluationMetrics
            Aggregate metrics
        results_df : pd.DataFrame
            Per-image results
        
        Returns
        -------
        tuple of (Path, Path)
            Paths to exported CSV and JSON files
        """
        # Export per-image results to CSV
        csv_path = self.outputs_dir / 'evaluation_report.csv'
        results_df.to_csv(csv_path, index=False)
        logger.info(f"Exported per-image results: {csv_path}")

        # Export field-level mismatch debug data -- the actual predicted vs
        # ground-truth strings for every matched pair, hallucination, and
        # missed medicine. This is what actually shows WHY a field failed,
        # instead of just that it failed.
        debug_path = self.outputs_dir / 'field_debug.csv'
        if metrics.debug_rows:
            debug_df = pd.DataFrame(metrics.debug_rows)
            debug_df.to_csv(debug_path, index=False)
            logger.info(f"Exported field-level debug data: {debug_path}")
        else:
            logger.info("No debug rows to export (empty dataset)")
        
        # Export summary to JSON
        summary = metrics.calculate_aggregates()
        json_path = self.outputs_dir / 'summary.json'
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2)
        
        logger.info(f"Exported summary: {json_path}")
        
        # Print summary to console
        logger.info("\n" + "="*70)
        logger.info("EVALUATION SUMMARY")
        logger.info("="*70)
        
        for key, value in summary.items():
            logger.info(f"  {key}: {value}")
        
        logger.info("="*70 + "\n")
        
        return csv_path, json_path


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

async def run_full_evaluation(
    skip_fallback: bool = False,
    limit: Optional[int] = None
) -> Dict:
    """
    Run complete evaluation and export results.
    
    Parameters
    ----------
    skip_fallback : bool, optional
        Skip fallback for faster evaluation, by default False
    limit : int, optional
        Limit number of images, by default None
    
    Returns
    -------
    dict
        Summary metrics
    
    Examples
    --------
    >>> summary = await run_full_evaluation(limit=5)
    >>> print(f"F1 Score: {summary['f1_score']}")
    """
    evaluator = PrescriptionEvaluator()
    metrics, results_df = await evaluator.run_evaluation(
        skip_fallback=skip_fallback,
        limit=limit
    )
    evaluator.export_results(metrics, results_df)
    return metrics.calculate_aggregates()


async def quick_evaluation(n_images: int = 5) -> Dict:
    """
    Quick evaluation on a subset of images.
    
    Parameters
    ----------
    n_images : int, optional
        Number of images to evaluate, by default 5
    
    Returns
    -------
    dict
        Summary metrics
    """
    return await run_full_evaluation(skip_fallback=True, limit=n_images)