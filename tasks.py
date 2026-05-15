"""
Celery tasks — all background work goes here.

Task groups:
  ── Rating ──────────────────────────────────────────────────────────────────
  recalculate_all_ratings     periodic bulk recalculation (beat, hourly)
  recalculate_user_rating     single-user recalc (legacy alias, still used)

  ── Event pipeline (bot → MQ → worker) ──────────────────────────────────────
  process_like_event          record analytics + recalc recipient rating
  process_skip_event          record analytics
  process_match_event         record analytics + recalc both users
  process_message_event       record messaging analytics

  ── Cache ───────────────────────────────────────────────────────────────────
  warm_user_feed_cache        preload next feed batch for one user
  warm_active_users_cache     preload caches for recently active users (beat, 15 min)
  refresh_hot_profiles        rebuild hot_profiles sorted set (beat, 30 min)

  ── Maintenance ─────────────────────────────────────────────────────────────
  cleanup_old_data            purge stale analytics events (beat, daily 3 AM)
"""
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from celery_app import celery_app

logger = logging.getLogger(__name__)


# ── Rating tasks ──────────────────────────────────────────────────────────────

@celery_app.task(name="tasks.recalculate_all_ratings", bind=True, max_retries=3)
def recalculate_all_ratings(self) -> None:
    try:
        from app.modules.rating import recalculate_all_sync
        logger.info("[rating] Starting bulk recalculation")
        recalculate_all_sync()
        logger.info("[rating] Bulk recalculation done")
    except Exception as exc:
        logger.exception("[rating] Bulk recalculation failed")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="tasks.recalculate_user_rating", bind=True, max_retries=3)
def recalculate_user_rating(self, user_id_str: str) -> None:
    try:
        from app.modules.rating import recalculate_one_sync
        logger.info("[rating] Recalculating user=%s", user_id_str)
        recalculate_one_sync(user_id_str)
    except Exception as exc:
        logger.exception("[rating] Recalc failed user=%s", user_id_str)
        raise self.retry(exc=exc, countdown=10)


# ── Event pipeline tasks ──────────────────────────────────────────────────────

@celery_app.task(name="tasks.process_like_event", bind=True, max_retries=3)
def process_like_event(self, from_user_id: str, to_user_id: str) -> None:
    """
    Consumed after bot publishes a like_event.
    1. Record analytics row in user_events.
    2. Increment Redis daily counter (best-effort via DB).
    3. Recalculate rating for the liked user.
    """
    try:
        from app.modules.metrics import record_event_sync
        from app.modules.rating import recalculate_one_sync
        logger.info("[event:like] %s → %s", from_user_id, to_user_id)
        record_event_sync("like", from_user_id, to_user_id)
        recalculate_one_sync(to_user_id)
    except Exception as exc:
        logger.exception("[event:like] Failed %s→%s", from_user_id, to_user_id)
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="tasks.process_skip_event", bind=True, max_retries=3)
def process_skip_event(self, from_user_id: str, to_user_id: str) -> None:
    """
    Consumed after bot publishes a skip_event.
    Skips only update analytics; they do not affect the recipient's rating.
    """
    try:
        from app.modules.metrics import record_event_sync
        logger.info("[event:skip] %s → %s", from_user_id, to_user_id)
        record_event_sync("skip", from_user_id, to_user_id)
    except Exception as exc:
        logger.exception("[event:skip] Failed %s→%s", from_user_id, to_user_id)
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="tasks.process_match_event", bind=True, max_retries=3)
def process_match_event(self, user1_id: str, user2_id: str) -> None:
    """
    Consumed after bot publishes a match_event.
    Recalculates ratings for both users (match significantly boosts level2_score).
    """
    try:
        from app.modules.metrics import record_event_sync
        from app.modules.rating import recalculate_one_sync
        logger.info("[event:match] %s <-> %s", user1_id, user2_id)
        record_event_sync("match", user1_id, user2_id)
        recalculate_one_sync(user1_id)
        recalculate_one_sync(user2_id)
    except Exception as exc:
        logger.exception("[event:match] Failed %s<->%s", user1_id, user2_id)
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="tasks.process_message_event", bind=True, max_retries=3)
def process_message_event(self, sender_id: str, match_id: str) -> None:
    """Consumed after bot publishes a message_event (messaging analytics)."""
    try:
        from app.modules.metrics import record_event_sync
        logger.info("[event:message] sender=%s match=%s", sender_id, match_id)
        record_event_sync("message", sender_id, None)
    except Exception as exc:
        logger.exception("[event:message] Failed sender=%s", sender_id)
        raise self.retry(exc=exc, countdown=10)


# ── Cache tasks ───────────────────────────────────────────────────────────────

@celery_app.task(name="tasks.warm_user_feed_cache", bind=True, max_retries=2)
def warm_user_feed_cache(self, user_id_str: str) -> None:
    """
    Proactively load the next feed batch into Redis for a single user.
    Called from the bot after each like/skip so the user never waits for DB.
    """
    try:
        from app.modules.matching import warm_cache_sync
        logger.info("[cache:warm] user=%s", user_id_str)
        warm_cache_sync(user_id_str)
    except Exception as exc:
        logger.exception("[cache:warm] Failed user=%s", user_id_str)
        raise self.retry(exc=exc, countdown=5)


@celery_app.task(name="tasks.warm_active_users_cache", bind=True, max_retries=3)
def warm_active_users_cache(self) -> None:
    """
    Periodic task: warm feed caches for users active in the last 24 h.
    Runs every 15 minutes via beat.
    """
    try:
        from app.modules.matching import warm_active_users_sync
        logger.info("[cache:warm_active] Starting")
        warm_active_users_sync()
        logger.info("[cache:warm_active] Done")
    except Exception as exc:
        logger.exception("[cache:warm_active] Failed")
        raise self.retry(exc=exc, countdown=60)


@celery_app.task(name="tasks.refresh_hot_profiles", bind=True, max_retries=3)
def refresh_hot_profiles(self) -> None:
    """
    Periodic task: rebuild hot_profiles Redis sorted set (top-100 by final_score).
    Runs every 30 minutes via beat.
    """
    try:
        from app.modules.matching import refresh_hot_profiles_sync
        logger.info("[cache:hot_profiles] Refreshing")
        refresh_hot_profiles_sync()
        logger.info("[cache:hot_profiles] Done")
    except Exception as exc:
        logger.exception("[cache:hot_profiles] Failed")
        raise self.retry(exc=exc, countdown=60)


# ── Maintenance tasks ─────────────────────────────────────────────────────────

@celery_app.task(name="tasks.cleanup_old_data", bind=True, max_retries=3)
def cleanup_old_data(self) -> None:
    """
    Periodic task: remove analytics events older than 90 days.
    Runs daily at 03:00 via beat.
    """
    try:
        from app.modules.metrics import cleanup_sync
        logger.info("[cleanup] Starting")
        cleanup_sync()
        logger.info("[cleanup] Done")
    except Exception as exc:
        logger.exception("[cleanup] Failed")
        raise self.retry(exc=exc, countdown=300)
