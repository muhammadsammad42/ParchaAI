
"""
FastAPI backend for the ParchaAI Flutter app

Flow the Flutter app follows:
    1. POST /upload    
    2. GET  /status/{id}
    3. GET  /result/{id}  


And Redis itself running (local `redis-server`, or a free-tier hosted Redis).
"""

import base64
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from .celery_tasks import process_prescription_task
from .config import get_config, setup_logging
from .database import Prescription, get_db, init_db

setup_logging()
logger = logging.getLogger(__name__)
config = get_config()

app = FastAPI(
    title="ParchaAI API",
    description="Handwritten prescription -> structured data -> Urdu audio, for the ParchaAI Flutter app.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

AUDIO_DIR = config.outputs_dir / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

UPLOAD_DIR = config.raw_images_dir
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_FILE_SIZE_MB = 10


@app.on_event("startup")
async def on_startup():
    init_db()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("ParchaAI API started. Uploads: %s | Audio: %s", UPLOAD_DIR, AUDIO_DIR)


# =============================================================================
# HELPERS
# =============================================================================

def _to_audio_url(local_path: Optional[str], request: Request) -> Optional[str]:
    """Convert a local .mp3 path (as stored by TextToSpeechEngine) into a
    public URL served by the /audio static mount. Returns None if the
    medicine's audio failed to generate (local_path is None) or the file
    isn't actually under AUDIO_DIR for some reason."""
    if not local_path:
        return None
    filename = Path(local_path).name
    return str(request.base_url).rstrip("/") + f"/audio/{filename}"


def _attach_audio_urls(result: dict, request: Request) -> dict:
    """Rewrite local audio_path / combined_audio_path fields in a stored
    UrduPrescriptionResult dict into publicly reachable URLs, in place."""
    for medicine in result.get("medicines", []):
        medicine["audio_url"] = _to_audio_url(medicine.get("audio_path"), request)
        medicine.pop("audio_path", None)  # don't leak local server filesystem paths
    result["combined_audio_url"] = _to_audio_url(result.get("combined_audio_path"), request)
    result.pop("combined_audio_path", None)
    return result


# =============================================================================
# ROUTES
# =============================================================================

@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.post("/upload")
async def upload_prescription(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Accept a prescription image from the Flutter app, save it, queue
    background processing, and immediately return a prescription_id for
    the app to poll.
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({size_mb:.1f}MB). Max allowed is {MAX_FILE_SIZE_MB}MB.",
        )
    if size_mb == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    prescription_id = str(uuid.uuid4())
    image_path = UPLOAD_DIR / f"{prescription_id}{ext}"

    with open(image_path, "wb") as f:
        f.write(contents)

    image_b64 = base64.b64encode(contents).decode("utf-8")

    record = Prescription(
        id=prescription_id,
        image_path=str(image_path),
        image_data=image_b64,
        status="pending",
    )
    db.add(record)
    db.commit()

    process_prescription_task.delay(prescription_id, str(image_path))
    logger.info("Queued prescription %s (%s, %.2fMB)", prescription_id, ext, size_mb)

    return {"prescription_id": prescription_id, "status": "pending"}


@app.get("/status/{prescription_id}")
async def get_status(prescription_id: str, db: Session = Depends(get_db)):
    """Lightweight poll target: just the current lifecycle status."""
    record = db.query(Prescription).filter_by(id=prescription_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Prescription not found")

    return {
        "prescription_id": prescription_id,
        "status": record.status,  # pending | processing | done | failed
        "error": record.error_message if record.status == "failed" else None,
    }


@app.get("/result/{prescription_id}")
async def get_result(prescription_id: str, request: Request, db: Session = Depends(get_db)):
    """
    Full payload once processing is done: extracted medicines, Urdu
    instruction text per medicine, and playable audio URLs.

    Returns 409 (not an error, just "not ready") if still pending/processing,
    so the Flutter app can distinguish "keep polling" from "something broke".
    """
    record = db.query(Prescription).filter_by(id=prescription_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Prescription not found")

    if record.status in ("pending", "processing"):
        raise HTTPException(
            status_code=409,
            detail=f"Result not ready yet (status: {record.status}). Keep polling /status.",
        )

    if record.status == "failed":
        raise HTTPException(status_code=500, detail=record.error_message or "Processing failed")

    result = json.loads(record.result_json)
    result = _attach_audio_urls(result, request)
    return result


@app.delete("/prescription/{prescription_id}")
async def delete_prescription(prescription_id: str, db: Session = Depends(get_db)):
    record = db.query(Prescription).filter_by(id=prescription_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Prescription not found")
    db.delete(record)
    db.commit()
    return {"deleted": prescription_id}