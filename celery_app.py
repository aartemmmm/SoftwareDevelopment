"""
Celery application — брокер RabbitMQ, результаты через rpc://.

Запуск воркера:
    celery -A celery_app worker -l info

Запуск планировщика (beat):
    celery -A celery_app beat -l info
"""
import os
import sys
from pathlib import Path

# Гарантируем, что корень проекта в sys.path независимо от того,
# из какой директории запущен воркер
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
    # Периодический пересчёт всех рейтингов — каждый час
    beat_schedule={
        "recalculate-all-ratings-hourly": {
            "task": "tasks.recalculate_all_ratings",
            "schedule": crontab(minute=0),
        },
    },
)
