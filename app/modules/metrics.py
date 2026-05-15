"""
Metrics and analytics module.

Two storage layers:
  1. Redis  — real-time counters (today's likes / skips / matches, active users)
  2. DB     — UserEvent table for historical queries and conversion analytics

Public async API (used by bot handlers):
  increment_event(event_type, redis)
  get_daily_stats(redis) → dict
  record_event_async(event_type, from_user_id, to_user_id, session)

Sync API (used by Celery workers):
  record_event_sync(event_type, from_id, to_id)
  cleanup_sync()
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── Redis key templates ───────────────────────────────────────────────────────
_K_LIKES   = "metrics:likes:{date}"
_K_SKIPS   = "metrics:skips:{date}"
_K_MATCHES = "metrics:matches:{date}"
_K_ACTIVE  = "metrics:active_users:{date}"
_COUNTER_TTL = 86400 * 3   # keep 3 days of counters in Redis


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


# ── Async API ─────────────────────────────────────────────────────────────────

_K_HOURLY  = "metrics:hourly:{date}:{event_type}"


async def increment_event(event_type: str, redis) -> None:
    """Increment the real-time Redis counter for the given event type."""
    date = _today()
    key_map = {
        "like":  _K_LIKES.format(date=date),
        "skip":  _K_SKIPS.format(date=date),
        "match": _K_MATCHES.format(date=date),
    }
    key = key_map.get(event_type)
    if key:
        await redis.incr(key)
        await redis.expire(key, _COUNTER_TTL)


async def record_hourly_activity(event_type: str, redis) -> None:
    """
    Increment the hourly bucket for an event type.
    Key format: metrics:hourly:2026-05-15:like  → hash field '14' (hour)
    Enables time-of-day activity pattern analysis.
    """
    hour = str(datetime.utcnow().hour)
    key  = _K_HOURLY.format(date=_today(), event_type=event_type)
    await redis.hincrby(key, hour, 1)
    await redis.expire(key, _COUNTER_TTL)


async def get_hourly_pattern(event_type: str, redis) -> dict[str, int]:
    """
    Return today's hour-by-hour distribution for an event type.
    Example: {'9': 12, '10': 34, '14': 87, ...}
    """
    key  = _K_HOURLY.format(date=_today(), event_type=event_type)
    raw  = await redis.hgetall(key)
    return {hour: int(count) for hour, count in raw.items()}


async def mark_user_active(user_id: uuid.UUID, redis) -> None:
    """Add user to today's active-users HyperLogLog set."""
    key = _K_ACTIVE.format(date=_today())
    await redis.pfadd(key, str(user_id))
    await redis.expire(key, _COUNTER_TTL)


async def get_daily_stats(redis) -> dict:
    """Return today's event statistics from Redis."""
    date = _today()
    likes   = int(await redis.get(_K_LIKES.format(date=date))   or 0)
    skips   = int(await redis.get(_K_SKIPS.format(date=date))   or 0)
    matches = int(await redis.get(_K_MATCHES.format(date=date)) or 0)
    active  = int(await redis.pfcount(_K_ACTIVE.format(date=date)) or 0)

    conversion = round(matches / likes * 100, 1) if likes > 0 else 0.0

    return {
        "date":              date,
        "likes":             likes,
        "skips":             skips,
        "matches":           matches,
        "active_users":      active,
        "like_match_rate_%": conversion,
    }


async def record_event_async(
    event_type: str,
    from_user_id: uuid.UUID,
    to_user_id: uuid.UUID | None,
    session,
) -> None:
    """Persist a domain event to the UserEvent table inside an open session."""
    from app.db.models import UserEvent

    session.add(
        UserEvent(
            user_id=from_user_id,
            target_id=to_user_id,
            event_type=event_type,
        )
    )
    await session.flush()


# ── Sync helpers (Celery workers) ─────────────────────────────────────────────

async def _record_event(
    event_type: str,
    from_id: str,
    to_id: str | None,
) -> None:
    from app.db.base import async_session
    from app.db.models import UserEvent

    from_uid = uuid.UUID(from_id)
    to_uid   = uuid.UUID(to_id) if to_id else None

    async with async_session() as session:
        async with session.begin():
            session.add(
                UserEvent(
                    user_id=from_uid,
                    target_id=to_uid,
                    event_type=event_type,
                )
            )


def record_event_sync(
    event_type: str,
    from_id: str,
    to_id: str | None = None,
) -> None:
    """Celery entry point: write a UserEvent row."""
    try:
        asyncio.run(_record_event(event_type, from_id, to_id))
    except Exception:
        logger.exception("record_event_sync failed event=%s", event_type)


async def _cleanup_old_events(retention_days: int = 90) -> None:
    from sqlalchemy import delete
    from app.db.base import async_session
    from app.db.models import UserEvent

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(
                delete(UserEvent).where(UserEvent.created_at < cutoff)
            )
            deleted = result.rowcount
    logger.info("Cleanup: removed %d UserEvent rows older than %d days", deleted, retention_days)


def cleanup_sync(retention_days: int = 90) -> None:
    """Celery entry point: purge old analytics events."""
    asyncio.run(_cleanup_old_events(retention_days))


# ── DB analytics queries ──────────────────────────────────────────────────────

async def get_conversion_stats(session, days: int = 7) -> dict:
    """
    Return like→match conversion rate for the last N days.
    Used for admin/analytics reporting.
    """
    from sqlalchemy import func, select
    from app.db.models import UserEvent

    cutoff = datetime.utcnow() - timedelta(days=days)

    likes_row = await session.scalar(
        select(func.count(UserEvent.id))
        .where(UserEvent.event_type == "like")
        .where(UserEvent.created_at >= cutoff)
    )
    matches_row = await session.scalar(
        select(func.count(UserEvent.id))
        .where(UserEvent.event_type == "match")
        .where(UserEvent.created_at >= cutoff)
    )

    likes   = likes_row   or 0
    matches = matches_row or 0
    rate    = round(matches / likes * 100, 1) if likes > 0 else 0.0

    return {
        "period_days":    days,
        "likes":          likes,
        "matches":        matches,
        "conversion_%":   rate,
    }
