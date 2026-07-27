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
        self.correct_confidence_sum = 0.0
        self.correct_count = 0
        self.incorrect_confidence_sum = 0.0
        self.incorrect_count = 0
        self.incorrect_flagged_count = 0  

        self.total_inference_time = 0.0
        
        self.per_image_results = []
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

        macro_field_accuracy = round(
            (medicine_name_accuracy + dosage_accuracy + frequency_accuracy + duration_accuracy) / 4,
            2
        )

        clinical_weighted_accuracy = round(
            medicine_name_accuracy * CLINICAL_WEIGHTS['medicine_name']
            + dosage_accuracy * CLINICAL_WEIGHTS['dosage']
            + frequency_accuracy * CLINICAL_WEIGHTS['frequency']
            + duration_accuracy * CLINICAL_WEIGHTS['duration'],
            2
        )

        avg_confidence_correct = (
            round(self.correct_confidence_sum / self.correct_count, 3)
            if self.correct_count > 0 else None
        )
        avg_confidence_incorrect = (
            round(self.incorrect_confidence_sum / self.incorrect_count, 3)
            if self.incorrect_count > 0 else None
        )

        human_review_catch_rate = (
            round((self.incorrect_flagged_count / self.incorrect_count) * 100, 2)
            if self.incorrect_count > 0 else None
        )

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
        name_match = medicine_names_match(pred_name_raw, truth_name_raw)
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
                results['purpose_match'] = fuzz.token_set_ratio(
                    pred_purpose.lower(), truth_purpose.lower()
                ) >= 80

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
        
        pred_name = strip_form_words(normalize_text(predicted.get('medicine_name', '')))
        truth_name = strip_form_words(normalize_text(ground_truth.get('medicine_name', '')))

        if not pred_name and not truth_name:
            return 100.0
        if not pred_name or not truth_name:
            return 0.0

        return float(fuzz.token_set_ratio(pred_name, truth_name))

    def _build_assignment_pairs(
        self,
        predicted_medicines: List[Dict],
        ground_truth_rows: List[Dict]
    ) -> List[Tuple[int, int]]:
        
        n_predicted = len(predicted_medicines)
        n_truth = len(ground_truth_rows)

        if n_predicted == 0 or n_truth == 0:
            return []

        matching_penalty = 10000.0
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
            'purpose_gradable': 0,  
            'exact_matches': 0,
            'hallucinations': 0,
            'false_negatives': 0,
            'processing_time': prediction.extraction_time_seconds or 0.0,
            'used_fallback': prediction.fallback_model_used,
            'correct_confidence_sum': 0.0,
            'correct_count': 0,
            'incorrect_confidence_sum': 0.0,
            'incorrect_count': 0,
            'incorrect_flagged_count': 0,
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
                image_key = image_path.stem  
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
                metrics.debug_rows.extend(image_results.pop('debug_rows', []))

                metrics.per_image_results.append(image_results)
                
                logger.info(
                    f"  Result: {image_results['medicine_name_correct']}/{image_results['n_truth']} "
                    f"correct names, {image_results['exact_matches']} exact matches"
                )
            
            except Exception as e:
                logger.error(
                    f"SKIPPING {image_path.name} -- this will reduce total_images "
                    f"below the full dataset size. Reason: {e}",
                    exc_info=True
                )
                continue

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
        
        # Export per-image results to CSV
        csv_path = self.outputs_dir / 'evaluation_report.csv'
        results_df.to_csv(csv_path, index=False)
        logger.info(f"Exported per-image results: {csv_path}")
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