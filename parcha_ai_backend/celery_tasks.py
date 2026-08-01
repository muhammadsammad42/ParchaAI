import asyncio
import base64
import json
import logging
import tempfile
from pathlib import Path

from .celery_app import celery_app
from .database import AudioClip, Prescription, SessionLocal
from .urdu_pipeline import UrduPipeline

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="parcha_ai.process_prescription", max_retries=0)
def process_prescription_task(self, prescription_id: str, image_path: str) -> dict:
    """
    Background task: process one prescription image end-to-end.

    Parameters
    ----------
    prescription_id : str
        Primary key of the Prescription row to update.
    image_path : str
        Path to the saved upload on the WEB service's disk (not readable
        here, since the worker is a separate container/filesystem -- kept
        only to preserve the file extension). The actual image bytes are
        reconstructed from record.image_data (base64, stored in the DB).

    Returns
    -------
    dict
        Small status summary (the full result lives in the DB row / is
        fetched via /result, not returned through Celery's result backend,
        to avoid duplicating potentially large JSON+audio-path payloads).
    """
    db = SessionLocal()
    record = db.query(Prescription).filter_by(id=prescription_id).first()

    if record is None:
        db.close()
        logger.error("Task fired for unknown prescription_id=%s", prescription_id)
        return {"status": "failed", "prescription_id": prescription_id, "error": "record not found"}

    tmp_path = None
    try:
        record.status = "processing"
        db.commit()

        if record.image_data:
            image_bytes = base64.b64decode(record.image_data)
            suffix = Path(image_path).suffix or ".jpg"
            tmp_file = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp_file.write(image_bytes)
            tmp_file.close()
            tmp_path = tmp_file.name
            local_image_path = tmp_path
        else:
            # Fallback for older records without image_data (pre-migration)
            local_image_path = image_path

        pipeline = UrduPipeline()
        result = asyncio.run(pipeline.process_image(local_image_path))

        # NEW: persist generated audio bytes to the DB, since the worker's
        # local /app/outputs/audio files are not visible to the web
        # service (separate container/filesystem, no shared volume).
        for medicine in result.medicines:
            if medicine.audio_path and Path(medicine.audio_path).exists():
                with open(medicine.audio_path, "rb") as f:
                    audio_b64 = base64.b64encode(f.read()).decode("utf-8")
                db.add(AudioClip(
                    prescription_id=prescription_id,
                    filename=Path(medicine.audio_path).name,
                    audio_data=audio_b64,
                ))

        if result.combined_audio_path and Path(result.combined_audio_path).exists():
            with open(result.combined_audio_path, "rb") as f:
                combined_b64 = base64.b64encode(f.read()).decode("utf-8")
            db.add(AudioClip(
                prescription_id=prescription_id,
                filename=Path(result.combined_audio_path).name,
                audio_data=combined_b64,
            ))

        record.status = "done"
        record.result_json = result.to_json()
        record.error_message = None
        db.commit()

        logger.info("Prescription %s processed successfully", prescription_id)
        return {"status": "done", "prescription_id": prescription_id}

    except Exception as exc:
        logger.exception("Processing failed for prescription %s", prescription_id)
        record.status = "failed"
        record.error_message = str(exc)
        db.commit()
        return {"status": "failed", "prescription_id": prescription_id, "error": str(exc)}

    finally:
        db.close()
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass