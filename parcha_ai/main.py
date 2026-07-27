"""
Command-line interface for ParchaAI prescription extraction system.

This module provides CLI commands for:
- Single image processing
- Batch image processing
- Full evaluation against ground truth dataset
- Quick testing with sample images
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from .config import get_config, setup_logging
from .evaluation import run_full_evaluation, quick_evaluation
from .pipeline import ParchaAIPipeline
from .validation import PrescriptionResponse

logger = logging.getLogger(__name__)


def setup_cli_logging(verbose: bool = False):
    """
    Setup logging for CLI usage.
    
    Parameters
    ----------
    verbose : bool, optional
        Enable verbose debug logging, by default False
    """
    level = logging.DEBUG if verbose else logging.INFO
    setup_logging(level=level)


async def process_single_image(
    image_path: str,
    output_path: Optional[str] = None,
    skip_fallback: bool = False,
    verbose: bool = False
) -> PrescriptionResponse:
    """
    Process a single prescription image.
    
    Parameters
    ----------
    image_path : str
        Path to prescription image
    output_path : str, optional
        Path to save JSON output, by default None (prints to stdout)
    skip_fallback : bool, optional
        Skip fallback verification, by default False
    verbose : bool, optional
        Enable verbose logging, by default False
    
    Returns
    -------
    PrescriptionResponse
        Extraction result
    """
    setup_cli_logging(verbose)
    
    logger.info(f"Processing: {image_path}")
    
    # Initialize pipeline
    pipeline = ParchaAIPipeline()
    
    # Process image
    result = await pipeline.process_image(
        image_path,
        skip_fallback=skip_fallback
    )
    
    # Get statistics
    stats = pipeline.get_statistics(result)
    
    logger.info("\n" + "="*60)
    logger.info("EXTRACTION SUMMARY")
    logger.info("="*60)
    logger.info(f"Image: {Path(result.image_path).name if result.image_path else result.prescription_id}")
    logger.info(f"Medicines extracted: {stats['total_medicines']}")
    logger.info(f"Found in local DB: {stats['found_in_local_db']}")
    logger.info(f"Found in OpenFDA: {stats['found_in_openfda']}")
    logger.info(f"Not found: {stats['not_found']}")
    logger.info(f"Low confidence: {stats['low_confidence']}")
    logger.info(f"Requires review: {stats['requires_review']}")
    logger.info(f"Average confidence: {stats['avg_confidence']:.3f}")
    logger.info(f"Processing time: {stats['processing_time']:.2f}s")
    logger.info(f"Used fallback: {stats['used_fallback']}")
    logger.info("="*60 + "\n")
    
    # Output result
    result_json = result.model_dump_json(indent=2)
    
    if output_path:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(result_json)
        
        logger.info(f"Saved result to: {output_file}")
    else:
        print("\n" + result_json)
    
    return result


async def process_batch(
    images_dir: str,
    output_dir: Optional[str] = None,
    skip_fallback: bool = False,
    verbose: bool = False
):
    """
    Process multiple prescription images.
    
    Parameters
    ----------
    images_dir : str
        Directory containing prescription images
    output_dir : str, optional
        Directory to save JSON outputs, by default None
    skip_fallback : bool, optional
        Skip fallback verification, by default False
    verbose : bool, optional
        Enable verbose logging, by default False
    """
    setup_cli_logging(verbose)
    
    images_path = Path(images_dir)
    
    if not images_path.exists():
        logger.error(f"Images directory not found: {images_dir}")
        sys.exit(1)
    
    # Get all image paths
    image_paths = sorted(images_path.glob('*.jpg'))
    
    if not image_paths:
        logger.error(f"No .jpg images found in: {images_dir}")
        sys.exit(1)
    
    logger.info(f"Found {len(image_paths)} images to process")
    
    # Initialize pipeline
    pipeline = ParchaAIPipeline()
    
    # Process batch
    results = await pipeline.process_batch(
        image_paths,
        skip_fallback=skip_fallback
    )
    
    logger.info(f"\nProcessed {len(results)}/{len(image_paths)} images successfully")
    
    # Save outputs if directory specified
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for result in results:
            output_file = output_path / f"{result.prescription_id}.json"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(result.model_dump_json(indent=2))
        
        logger.info(f"Saved {len(results)} results to: {output_dir}")
    
    # Safe Summary Calculation to prevent Division by Zero
    total_medicines = sum(len(r.extracted_medicines) for r in results)
    if len(results) > 0:
        avg_time = sum(r.extraction_time_seconds or 0.0 for r in results) / len(results)
    else:
        avg_time = 0.0
    
    logger.info("\n" + "="*60)
    logger.info("BATCH PROCESSING SUMMARY")
    logger.info("="*60)
    logger.info(f"Images processed: {len(results)}")
    logger.info(f"Total medicines: {total_medicines}")
    logger.info(f"Average processing time: {avg_time:.2f}s")
    logger.info("="*60 + "\n")


async def run_evaluation(
    skip_fallback: bool = False,
    limit: Optional[int] = None,
    verbose: bool = False
):
    """
    Run full evaluation against ground truth dataset.
    
    Parameters
    ----------
    skip_fallback : bool, optional
        Skip fallback verification, by default False
    limit : int, optional
        Limit number of images to evaluate, by default None
    verbose : bool, optional
        Enable verbose logging, by default False
    """
    setup_cli_logging(verbose)
    
    logger.info("Starting evaluation suite")
    
    if limit:
        logger.info(f"Limiting evaluation to {limit} images")
    
    # Run evaluation
    summary = await run_full_evaluation(
        skip_fallback=skip_fallback,
        limit=limit
    )
    
    logger.info("\nEvaluation complete!")
    logger.info(f"Results saved to: {get_config().outputs_dir}")
    
    return summary


async def quick_test(n_images: int = 3, verbose: bool = False):
    """
    Quick test on a few images.
    
    Parameters
    ----------
    n_images : int, optional
        Number of images to test, by default 3
    verbose : bool, optional
        Enable verbose logging, by default False
    """
    setup_cli_logging(verbose)
    
    logger.info(f"Running quick test on {n_images} images")
    
    summary = await quick_evaluation(n_images=n_images)
    
    logger.info("\nQuick test complete!")
    logger.info(f"F1 Score: {summary['f1_score']}")
    logger.info(f"Medicine Name Accuracy: {summary['medicine_name_accuracy']}%")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description='ParchaAI - Handwritten Prescription Extraction System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process single image
  python -m parcha_ai.main process image.jpg
  
  # Process single image and save to file
  python -m parcha_ai.main process image.jpg -o result.json
  
  # Process batch of images
  python -m parcha_ai.main batch ./images/ -o ./outputs/
  
  # Run full evaluation
  python -m parcha_ai.main evaluate
  
  # Quick test on 5 images
  python -m parcha_ai.main test --n-images 5
  
  # Enable verbose logging
  python -m parcha_ai.main process image.jpg -v
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Process command
    process_parser = subparsers.add_parser(
        'process',
        help='Process a single prescription image'
    )
    process_parser.add_argument(
        'image',
        type=str,
        help='Path to prescription image'
    )
    process_parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output JSON file path (default: print to stdout)'
    )
    process_parser.add_argument(
        '--skip-fallback',
        action='store_true',
        help='Skip fallback verification for faster processing'
    )
    process_parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    # Batch command
    batch_parser = subparsers.add_parser(
        'batch',
        help='Process multiple prescription images'
    )
    batch_parser.add_argument(
        'images_dir',
        type=str,
        help='Directory containing prescription images'
    )
    batch_parser.add_argument(
        '-o', '--output-dir',
        type=str,
        help='Output directory for JSON files'
    )
    batch_parser.add_argument(
        '--skip-fallback',
        action='store_true',
        help='Skip fallback verification for faster processing'
    )
    batch_parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    # Evaluate command
    eval_parser = subparsers.add_parser(
        'evaluate',
        help='Run evaluation against ground truth dataset'
    )
    eval_parser.add_argument(
        '--skip-fallback',
        action='store_true',
        help='Skip fallback verification for faster evaluation'
    )
    eval_parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of images to evaluate'
    )
    eval_parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    # Test command
    test_parser = subparsers.add_parser(
        'test',
        help='Quick test on a few images'
    )
    test_parser.add_argument(
        '--n-images',
        type=int,
        default=3,
        help='Number of images to test (default: 3)'
    )
    test_parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose debug logging'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Handle no command
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    # Execute command
    try:
        if args.command == 'process':
            asyncio.run(process_single_image(
                image_path=args.image,
                output_path=args.output,
                skip_fallback=args.skip_fallback,
                verbose=args.verbose
            ))
        
        elif args.command == 'batch':
            asyncio.run(process_batch(
                images_dir=args.images_dir,
                output_dir=args.output_dir,
                skip_fallback=args.skip_fallback,
                verbose=args.verbose
            ))
        
        elif args.command == 'evaluate':
            asyncio.run(run_evaluation(
                skip_fallback=args.skip_fallback,
                limit=args.limit,
                verbose=args.verbose
            ))
        
        elif args.command == 'test':
            asyncio.run(quick_test(
                n_images=args.n_images,
                verbose=args.verbose
            ))
    
    except KeyboardInterrupt:
        logger.info("\nOperation cancelled by user")
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()