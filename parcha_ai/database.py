
"""
SQLite database layer for the ParchaAI FastAPI backend (Week 4).

Tracks every uploaded prescription through its lifecycle:
    pending -> processing -> done | failed

The Flutter app polls /status/{id} until status is "done" or "failed",
then fetches /result/{id} for the full extraction + Urdu + audio payload.
"""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import get_config

config = get_config()

# Keep the DB alongside the other project data (not inside outputs/, since
# outputs/ is also where per-run JSON/audio files live and gets treated as
# disposable artifact storage).
DB_PATH = config.project_root / "data" / "parcha_ai.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

# check_same_thread=False: FastAPI/Celery each open their own connections
# from different threads/processes; SQLite handles this fine for our
# read-light, write-light access pattern.
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Prescription(Base):
    """One row per uploaded prescription image."""

    __tablename__ = "prescriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    image_path = Column(String, nullable=False)
    status = Column(String, nullable=False, default="pending")  # pending|processing|done|failed
    result_json = Column(Text, nullable=True)   # UrduPrescriptionResult.to_json() once done
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def init_db() -> None:
    """Create tables if they don't exist yet. Safe to call on every startup."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency: yields a session, always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()