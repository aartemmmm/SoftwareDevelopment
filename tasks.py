"""
Celery tasks — фоновые задачи приложения.

recalculate_all_ratings  — периодический пересчёт рейтинга всех пользователей
recalculate_user_rating  — пересчёт рейтинга одного пользователя (event-driven,
                            вызывается из хендлера после лайка)
"""
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="tasks.recalculate_all_ratings", bind=True, max_retries=3)
def recalculate_all_ratings(self) -> None:  # type: ignore[override]
    """Периодически пересчитывает рейтинг всех пользователей."""
    try:
        from app.modules.rating import recalculate_all_sync
        logger.info("Starting periodic rating recalculation for all users")
        recalculate_all_sync()
        logger.info("Periodic rating recalculation completed")
    except Exception as exc:
        logger.exception("Error during periodic rating recalculation")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="tasks.recalculate_user_rating", bind=True, max_retries=3)
def recalculate_user_rating(self, user_id_str: str) -> None:  # type: ignore[override]
    """Пересчитывает рейтинг одного пользователя (event-driven после лайка)."""
    try:
        from app.modules.rating import recalculate_one_sync
        logger.info("Recalculating rating for user=%s", user_id_str)
        recalculate_one_sync(user_id_str)
    except Exception as exc:
        logger.exception("Error recalculating rating for user=%s", user_id_str)
        raise self.retry(exc=exc, countdown=10)
