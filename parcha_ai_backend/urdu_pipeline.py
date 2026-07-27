
"""
End-to-end Urdu explanation + audio pipeline for ParchaAI (Week 3).

Chains together everything built so far:

    Prescription Image
        |
        v
    ParchaAIPipeline (extraction, validation, RapidFuzz,
                       local DB, OpenFDA, confidence, Qwen fallback)
        |
        v
    PrescriptionResponse (validated MedicineDetail list)
        |
        v
    UrduExplainer (Groq Llama-3.3-70B text -> Urdu paragraph
                    per medicine)
        |
        v
    TextToSpeechEngine (gTTS -> .mp3 per medicine,
                         + one combined .mp3 per prescription)
        |
        v
    UrduPrescriptionResult (JSON-serializable, includes audio paths)

Drop this file into the `parcha_ai` package next to pipeline.py.

"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from .config import get_config
from .pipeline import ParchaAIPipeline
from .text_to_speech import TextToSpeechEngine, TTSError
from .urdu_explanation import UrduExplainer, UrduExplanationError
from .validation import PrescriptionResponse

logger = logging.getLogger(__name__)


class UrduPipelineError(Exception):
    """Raised when the Urdu explanation/audio stage fails unrecoverably."""
    pass


@dataclass
class MedicineAudioResult:
    """Urdu text + audio outcome for a single medicine."""
    medicine_name: str
    urdu_text: str
    audio_path: Optional[str]  # str, not Path, so this dataclass is JSON-friendly
    audio_generated: bool


@dataclass
class UrduPrescriptionResult:
    """
    Full Week 3 output for one prescription: the underlying validated
    extraction plus Urdu text and audio for every medicine.
    """
    prescription_id: str
    medicines: List[MedicineAudioResult] = field(default_factory=list)
    combined_audio_path: Optional[str] = None
    urdu_generation_time_seconds: float = 0.0
    audio_generation_time_seconds: float = 0.0
    total_time_seconds: float = 0.0
    extraction_response: Optional[dict] = None  # raw PrescriptionResponse.model_dump()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str)

    def save(self, output_path: Union[str, Path]) -> None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(self.to_json(), encoding="utf-8")
        logger.info(f"Saved Urdu pipeline result to: {output_path}")


class UrduPipeline:

    def __init__(
        self,
        extraction_pipeline: Optional[ParchaAIPipeline] = None,
        explainer: Optional[UrduExplainer] = None,
        tts_engine: Optional[TextToSpeechEngine] = None,
        combine_audio: bool = True,
    ):
        self.extraction_pipeline = extraction_pipeline or ParchaAIPipeline()
        self.explainer = explainer or UrduExplainer()
        self.tts_engine = tts_engine or TextToSpeechEngine()
        self.combine_audio = combine_audio

    async def process_prescription(
        self, response: PrescriptionResponse
    ) -> UrduPrescriptionResult:
        """
        Run the Urdu explanation + audio stage on an already-extracted
        PrescriptionResponse (skips image processing entirely).

        Parameters
        ----------
        response : PrescriptionResponse
            Output of ParchaAIPipeline.process_image / Week 1/2 pipeline.

        Returns
        -------
        UrduPrescriptionResult
        """
        overall_start = time.time()

        if not response.extracted_medicines:
            logger.warning(f"No medicines to explain for {response.prescription_id}")
            return UrduPrescriptionResult(
                prescription_id=response.prescription_id,
                extraction_response=response.model_dump(mode="json"),
            )

        # --- Urdu text generation -------------------------------------
        urdu_start = time.time()
        try:
            urdu_texts = await self.explainer.explain_all(response.extracted_medicines)
        except UrduExplanationError as e:
            raise UrduPipelineError(f"Urdu explanation failed: {e}")
        urdu_elapsed = time.time() - urdu_start

        # --- Audio synthesis --------------------------------------------
        audio_start = time.time()
        stems = [
            f"{response.prescription_id}_{i:02d}_{med.medicine_name}"
            for i, med in enumerate(response.extracted_medicines)
        ]
        audio_paths = self.tts_engine.synthesize_batch(urdu_texts, stems)
        audio_elapsed = time.time() - audio_start

        medicine_results = [
            MedicineAudioResult(
                medicine_name=med.medicine_name,
                urdu_text=text,
                audio_path=str(path) if path else None,
                audio_generated=path is not None,
            )
            for med, text, path in zip(response.extracted_medicines, urdu_texts, audio_paths)
        ]

        combined_path = None
        if self.combine_audio:
            combined = self.tts_engine.combine_audio(audio_paths, response.prescription_id)
            combined_path = str(combined) if combined else None

        total_elapsed = time.time() - overall_start

        result = UrduPrescriptionResult(
            prescription_id=response.prescription_id,
            medicines=medicine_results,
            combined_audio_path=combined_path,
            urdu_generation_time_seconds=round(urdu_elapsed, 3),
            audio_generation_time_seconds=round(audio_elapsed, 3),
            total_time_seconds=round(total_elapsed, 3),
            extraction_response=response.model_dump(mode="json"),
        )

        logger.info(
            f"Urdu pipeline complete for {response.prescription_id}: "
            f"{len(medicine_results)} medicines, "
            f"{sum(1 for m in medicine_results if m.audio_generated)} audio files, "
            f"{total_elapsed:.2f}s total"
        )
        return result

    async def process_image(
        self,
        image_path: Union[str, Path],
        skip_fallback: bool = False,
    ) -> UrduPrescriptionResult:
        """
        Full chain: image -> extraction (Week 1/2) -> Urdu + audio (Week 3).

        Parameters
        ----------
        image_path : str or Path
        skip_fallback : bool, optional
            Passed through to ParchaAIPipeline.process_image.

        Returns
        -------
        UrduPrescriptionResult
        """
        extraction_response = await self.extraction_pipeline.process_image(
            image_path, skip_fallback=skip_fallback
        )
        return await self.process_prescription(extraction_response)

    async def process_batch(
        self,
        image_paths: List[Union[str, Path]],
        skip_fallback: bool = False,
    ) -> List[UrduPrescriptionResult]:
        results = []
        for path in image_paths:
            try:
                results.append(await self.process_image(path, skip_fallback=skip_fallback))
            except Exception as e:
                logger.error(f"Failed to process {path}: {e}")
        return results


# =============================================================================
# CONVENIENCE FUNCTION
# =============================================================================

async def quick_urdu_process(image_path: Union[str, Path]) -> UrduPrescriptionResult:
    """One-liner for processing a single image end-to-end (image -> audio)."""
    pipeline = UrduPipeline()
    return await pipeline.process_image(image_path)