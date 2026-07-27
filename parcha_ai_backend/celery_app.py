
import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "parcha_ai",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["parcha_ai_backend.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=60 * 60 * 24,  
    task_track_started=True,
    task_soft_time_limit=180,
    task_time_limit=240,
)