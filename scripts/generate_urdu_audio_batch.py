"""
Phase 3 Module Integration Test

Tests all Phase 3 components:
- preprocessing.py
- extraction.py
- confidence.py
- pipeline.py
- evaluation.py
- main.py
"""

import asyncio
import sys
from pathlib import Path

def test_imports():
    """Test that all Phase 3 modules can be imported."""
    print("Testing Phase 3 imports...")
    
    try:
        from parcha_ai import (
            ParchaAIPipeline,
            quick_process,
            run_full_evaluation,
            quick_evaluation,
            PrescriptionResponse,
            MedicineDetail,
            normalize_text
        )
        from parcha_ai.preprocessing import (
            load_image,
            encode_image_to_base64,
            create_data_url,
            quick_encode
        )
        from parcha_ai.extraction import (
            VisionExtractor,
            QwenFallbackExtractor,
            parse_json_response
        )
        from parcha_ai.confidence import (
            ConfidenceScorer,
            FallbackRouter,
            calculate_confidence
        )
        from parcha_ai.pipeline import ParchaAIPipeline
        from parcha_ai.evaluation import PrescriptionEvaluator
        
        print("All Phase 3 imports successful!")
        return True
    
    except ImportError as e:
        print(f"Import error: {e}")
        return False


def test_preprocessing():
    """Test preprocessing module."""
    print("\nTesting preprocessing module...")
    
    try:
        from parcha_ai.preprocessing import is_valid_image_file
        from parcha_ai.config import get_config
        
        config = get_config()
        images_dir = config.datasets_dir / 'raw_images'
        
        # Check if any images exist
        if not images_dir.exists():
            print(f"Images directory not found: {images_dir}")
            return False
        
        images = list(images_dir.glob('*.jpg'))
        if not images:
            print(f"No JPG images found in {images_dir}")
            return False
        
        test_image = images[0]
        is_valid = is_valid_image_file(test_image)
        
        if is_valid:
            print(f"Image validation works: {test_image.name}")
            return True
        else:
            print(f"Image validation failed for {test_image.name}")
            return False
    
    except Exception as e:
        print(f"Preprocessing test error: {e}")
        return False


def test_extraction_setup():
    """Test extraction module initialization."""
    print("\nTesting extraction module...")
    
    try:
        from parcha_ai.extraction import VisionExtractor, QwenFallbackExtractor
        from parcha_ai.config import get_config
        
        config = get_config()
        
        # Check if API keys are configured
        if not config.groq_api_key:
            print("GROQ_API_KEY not configured in .env")
            return False
        
        # Initialize extractors
        primary = VisionExtractor()
        fallback = QwenFallbackExtractor()
        
        print(f"VisionExtractor initialized: {primary.model}")
        print(f"QwenFallbackExtractor initialized: {fallback.model}")
        
        return True
    
    except Exception as e:
        print(f"Extraction test error: {e}")
        return False


def test_confidence():
    """Test confidence scoring."""
    print("\nTesting confidence module...")
    
    try:
        from parcha_ai.confidence import ConfidenceScorer
        from parcha_ai.validation import MedicineDetail
        
        scorer = ConfidenceScorer(threshold=0.85)
        
        # Test medicine with good confidence
        good_medicine = MedicineDetail(
            medicine_name="Paracetamol",
            dosage="500mg",
            frequency="1-1-1",
            duration="5 days",
            purpose="fever",
            composition="Paracetamol 500mg",
            uses="pain relief",
            side_effects="nausea",
            precautions="liver disease",
            manufacturer="Test Pharma",
            confidence=0.0,
            found_in_local_db=True,
            found_in_openfda=False,
            low_confidence=False,
            requires_human_review=False
        )
        
        confidence = scorer.calculate_medicine_confidence(good_medicine, fuzzy_score=95)
        should_fallback = scorer.should_trigger_fallback(confidence)
        
        print(f"Confidence calculation works: {confidence:.3f}")
        print(f"Fallback decision: {'Yes' if should_fallback else 'No'}")
        
        return True
    
    except Exception as e:
        print(f"Confidence test error: {e}")
        return False


def test_pipeline_init():
    """Test pipeline initialization."""
    print("\nTesting pipeline module...")
    
    try:
        from parcha_ai.pipeline import ParchaAIPipeline
        
        pipeline = ParchaAIPipeline()
        
        print("Pipeline initialized successfully")
        print(f"  - Extractor: {pipeline.extractor.model}")
        print(f"  - Matcher: {pipeline.matcher.drug_count} medicines loaded")
        print(f"  - Router threshold: {pipeline.router.scorer.threshold}")
        
        return True
    
    except Exception as e:
        print(f"Pipeline test error: {e}")
        return False


def test_evaluation_setup():
    """Test evaluation module setup."""
    print("\nTesting evaluation module...")
    
    try:
        from parcha_ai.evaluation import PrescriptionEvaluator
        from parcha_ai.config import get_config
        
        config = get_config()
        evaluator = PrescriptionEvaluator()
        
        # Check if ground truth exists
        if not evaluator.ground_truth_path.exists():
            print(f"Ground truth not found: {evaluator.ground_truth_path}")
            return False
        
        # Load ground truth
        gt_df = evaluator.load_ground_truth()
        
        # Get image paths
        image_paths = evaluator.get_image_paths()
        
        print(f"Evaluator initialized")
        print(f"  - Ground truth entries: {len(gt_df)}")
        print(f"  - Images found: {len(image_paths)}")
        
        return True
    
    except Exception as e:
        print(f"Evaluation test error: {e}")
        return False


def test_main_cli():
    """Test main CLI module."""
    print("\nTesting main CLI module...")
    
    try:
        from parcha_ai import main
        
        # Just check that main function exists
        if hasattr(main, 'main'):
            print("CLI main() function exists")
            return True
        else:
            print("CLI main() function not found")
            return False
    
    except Exception as e:
        print(f"Main CLI test error: {e}")
        return False


async def test_extraction_parsing():
    """Test JSON parsing from extraction."""
    print("\nTesting JSON parsing...")
    
    try:
        from parcha_ai.extraction import parse_json_response
        
        # Test with clean JSON
        clean_json = '[{"medicine_name": "Test", "dosage": "500mg"}]'
        result1 = parse_json_response(clean_json)
        
        # Test with markdown fences
        markdown_json = '''```json
[{"medicine_name": "Test", "dosage": "500mg"}]
```'''
        result2 = parse_json_response(markdown_json)
        
        if result1 and result2:
            print("JSON parsing works (clean and markdown)")
            return True
        else:
            print("JSON parsing failed")
            return False
    
    except Exception as e:
        print(f"JSON parsing test error: {e}")
        return False


def run_all_tests():
    """Run all Phase 3 tests."""
    print("="*70)
    print("PHASE 3 MODULE INTEGRATION TESTS")
    print("="*70)
    
    results = []
    
    # Synchronous tests
    results.append(("Imports", test_imports()))
    results.append(("Preprocessing", test_preprocessing()))
    results.append(("Extraction Setup", test_extraction_setup()))
    results.append(("Confidence", test_confidence()))
    results.append(("Pipeline", test_pipeline_init()))
    results.append(("Evaluation", test_evaluation_setup()))
    results.append(("Main CLI", test_main_cli()))
    
    # Async tests
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If already in event loop, create new task
            results.append(("JSON Parsing", asyncio.run(test_extraction_parsing())))
        else:
            results.append(("JSON Parsing", loop.run_until_complete(test_extraction_parsing())))
    except:
        results.append(("JSON Parsing", asyncio.run(test_extraction_parsing())))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\nALL PHASE 3 TESTS PASSED!")
        print("\nNext steps:")
        print("1. Configure API keys in .env file")
        print("2. Run: python -m parcha_ai.main test --n-images 1")
        print("3. Run: python -m parcha_ai.main evaluate --limit 3")
        return True
    else:
        print("\n Some tests failed. Please fix issues before proceeding.")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
