"""
Celery application — broker: RabbitMQ, result backend: rpc://

Worker:
    celery -A celery_app worker -l info -c 4

Beat scheduler:
    celery -A celery_app beat -l info

Flower monitor (optional):
    celery -A celery_app flower
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from celery import Celery
from celery.schedules import crontab
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

_USER = os.environ.get("RABBITMQ_USER", "guest")
_PASS = os.environ.get("RABBITMQ_PASSWORD", "guest")
_HOST = os.environ.get("RABBITMQ_HOST", "localhost")
_PORT = os.environ.get("RABBITMQ_PORT", "5672")

BROKER_URL = f"amqp://{_USER}:{_PASS}@{_HOST}:{_PORT}//"

celery_app = Celery(
    "dating_bot",
    broker=BROKER_URL,
    backend="rpc://",
    include=["tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,

    # Retry settings
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Concurrency hint (overridden by -c flag)
    worker_prefetch_multiplier=1,

    beat_schedule={
        # ── Rating ─────────────────────────────────────────────────────────
        "recalculate-all-ratings-hourly": {
            "task": "tasks.recalculate_all_ratings",
            "schedule": crontab(minute=0),          # every hour at :00
        },

        # ── Cache ───────────────────────────────────────────────────────────
        "warm-active-users-cache-15min": {
            "task": "tasks.warm_active_users_cache",
            "schedule": crontab(minute="*/15"),     # every 15 minutes
        },
        "refresh-hot-profiles-30min": {
            "task": "tasks.refresh_hot_profiles",
            "schedule": crontab(minute="*/30"),     # every 30 minutes
        },

        # ── Maintenance ─────────────────────────────────────────────────────
        "cleanup-old-data-daily": {
            "task": "tasks.cleanup_old_data",
            "schedule": crontab(hour=3, minute=0),  # daily at 03:00
        },
    },
)
