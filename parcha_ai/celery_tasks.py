
"""
Celery task definitions for ParchaAI (Week 4).

There is exactly one task: run the full image -> extraction -> Urdu ->
audio chain (UrduPipeline, built in Week 1-3) for one prescription, and
write the result (or error) back to the prescriptions table so the
FastAPI /status and /result endpoints can serve it.
"""

import asyncio
import json
import logging

from .celery_app import celery_app
from .database import Prescription, SessionLocal
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
        Path to the saved upload on disk.

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

    try:
        record.status = "processing"
        db.commit()

        # UrduPipeline.process_image is async; Celery tasks are sync, so we
        # run our own event loop here. A fresh UrduPipeline() per task is
        # intentional -- avoids sharing HTTP clients/state across workers.
        pipeline = UrduPipeline()
        result = asyncio.run(pipeline.process_image(image_path))

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
        # Don't re-raise: we've already recorded the failure in the DB,
        # which is what /status and /result read from. Re-raising would
        # only make Celery log a second, redundant traceback.
        return {"status": "failed", "prescription_id": prescription_id, "error": str(exc)}

    finally:
        db.close()