
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import Column, DateTime, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import get_config

config = get_config()

# Allow DB_PATH override via environment variable for deployment
DB_PATH_ENV = os.getenv("DB_PATH")
if DB_PATH_ENV:
    DB_PATH = Path(DB_PATH_ENV)
else:
    DB_PATH = config.project_root / "data" / "parcha_ai.db"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
DATABASE_URL = f"sqlite:///{DB_PATH}"

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
    import logging
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:
        logging.getLogger(__name__).warning(
            f"init_db: create_all raised (likely tables already exist): {exc}"
        )


def get_db():
    """FastAPI dependency: yields a session, always closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
