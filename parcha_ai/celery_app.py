"""
Celery application instance for ParchaAI (Week 4).

Kept in its own module (separate from celery_tasks.py) so both
celery_tasks.py and api.py can import `celery_app` without a circular
import between "the app" and "the tasks registered on it".

Run a worker with:
    celery -A parcha_ai.celery_app worker --loglevel=info --concurrency=2

`--concurrency=2` (not higher) is deliberate: the VLM/Groq calls inside
each task are already rate-limited (see config.inter_request_delay_seconds),
so running many tasks in parallel just means many workers independently
racing against the same free-tier API quota.
"""

import os

from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "parcha_ai",
    broker=REDIS_URL,
    backend=REDIS_URL,
    # Without this, `celery -A parcha_ai.celery_app worker` only loads THIS
    # file -- it never imports celery_tasks.py, so the @celery_app.task
    # decorator in that file never runs and the task never registers.
    # The worker then receives "parcha_ai.process_prescription" messages
    # from the queue but has no matching task and silently discards them
    # (logged as "Received unregistered task of type ..."). `include`
    # tells Celery to import celery_tasks.py itself once the app object
    # exists, which avoids the circular import that would happen if we
    # imported celery_tasks directly at the top of this file (celery_tasks
    # imports celery_app, so celery_app can't import celery_tasks back at
    # module load time).
    include=["parcha_ai.celery_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=60 * 60 * 24,  # keep task results for 24h
    task_track_started=True,
    # A single prescription (extraction + Urdu + TTS for multiple medicines)
    # can legitimately take a minute or two; don't let Celery kill it early.
    task_soft_time_limit=180,
    task_time_limit=240,
)