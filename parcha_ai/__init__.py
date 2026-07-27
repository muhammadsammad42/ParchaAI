"""
ParchaAI - AI-Powered Handwritten Prescription Decoding System

This package provides a modular, production-ready pipeline for extracting
structured medication information from handwritten prescription images.

Core Components
---------------
- config: Configuration management
- prompts: Prompt templates for vision models
- preprocessing: Image preprocessing pipeline
- extraction: Two-pass extraction with fallback verification
- validation: Pydantic schemas and field validation
- fuzzy_match: Local drug database matching with RapidFuzz
- openfda: Global drug validation via OpenFDA API
- confidence: Confidence scoring and routing logic
- evaluation: Metrics calculation and benchmarking
- pipeline: End-to-end orchestration

Usage
-----
Basic extraction:
     from parcha_ai import quick_process
     import asyncio
     result = asyncio.run(quick_process("path/to/prescription.jpg"))

Full evaluation:
     from parcha_ai import run_full_evaluation
     import asyncio
     metrics = asyncio.run(run_full_evaluation())
"""

__version__ = "0.1.0"
__author__ = "Sammad"

from .config import Config, get_config, reload_config
from .validation import PrescriptionResponse, MedicineDetail
from .utils import normalize_text


def __getattr__(name: str):
    if name in {"ParchaAIPipeline", "quick_process"}:
        from .pipeline import ParchaAIPipeline, quick_process
        return {"ParchaAIPipeline": ParchaAIPipeline, "quick_process": quick_process}[name]
    if name in {"run_full_evaluation", "quick_evaluation"}:
        from .evaluation import run_full_evaluation, quick_evaluation
        return {"run_full_evaluation": run_full_evaluation, "quick_evaluation": quick_evaluation}[name]
    raise AttributeError(name)

__all__ = [
    "Config",
    "get_config",
    "reload_config",
    "ParchaAIPipeline",
    "quick_process",
    "run_full_evaluation",
    "quick_evaluation",
    "PrescriptionResponse",
    "MedicineDetail",
    "normalize_text",
    "__version__",
]
