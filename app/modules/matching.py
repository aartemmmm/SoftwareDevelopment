"""
Matching module — feed candidate selection and cache management.

Feed pipeline:
  1. pop_from_feed()       — try Redis cache first (O(1))
  2. _get_candidate_ids()  — if cache empty: query DB, sort by final_score DESC
  3. load remaining IDs back into Redis (next-batch prefetch)

Hot profiles cache (Redis sorted set):
  Key: hot_profiles
  Score: final_score
  Used by: Celery periodic task to keep top-100 pre-ranked
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy import and_, distinct, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Interaction, Match, Preferences, Profile, Rating, User
from app.modules import cache as cache_module

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10
_HOT_PROFILES_KEY = "hot_profiles"
_HOT_PROFILES_TTL = 1800  # 30 min


# ── Internal DB query ─────────────────────────────────────────────────────────

async def _get_candidate_ids(
    user_id: uuid.UUID,
    session: AsyncSession,
    limit: int = _BATCH_SIZE,
) -> list[uuid.UUID]:
    prefs = await session.scalar(
        select(Preferences).where(Preferences.user_id == user_id)
    )

    interacted_subq = (
        select(Interaction.to_user_id)
        .where(Interaction.from_user_id == user_id)
        .scalar_subquery()
    )

    query = (
        select(User.id)
        .join(Profile, Profile.user_id == User.id)
        .outerjoin(Rating, Rating.user_id == User.id)
        .where(User.id != user_id)
        .where(User.id.not_in(interacted_subq))
    )

    if prefs:
        if prefs.preferred_gender != "any":
            query = query.where(Profile.gender == prefs.preferred_gender)
        query = query.where(Profile.age >= prefs.min_age)
        query = query.where(Profile.age <= prefs.max_age)

    query = query.order_by(Rating.final_score.desc().nullslast()).limit(limit)

    result = await session.scalars(query)
    return list(result.all())


# ── Public feed API ───────────────────────────────────────────────────────────

async def get_next_profile_id(
    user_id: uuid.UUID,
    session: AsyncSession,
    redis: Redis,
) -> Optional[uuid.UUID]:
    """
    Return next profile UUID for the feed.
    Cache-first: pop from Redis; on miss load a fresh batch from DB.
    """
    cached_id = await cache_module.pop_from_feed(user_id, redis)
    if cached_id:
        return cached_id

    candidates = await _get_candidate_ids(user_id, session, limit=_BATCH_SIZE)
    if not candidates:
        return None

    # Store remaining IDs for subsequent requests
    if len(candidates) > 1:
        await cache_module.load_feed_cache(user_id, candidates[1:], redis)

    return candidates[0]


async def record_interaction(
    from_user_id: uuid.UUID,
    to_user_id: uuid.UUID,
    action: str,
    session: AsyncSession,
) -> Optional[Match]:
    """
    Persist a like / skip interaction.
    On mutual like: create a Match record and return it.
    """
    session.add(
        Interaction(
            from_user_id=from_user_id,
            to_user_id=to_user_id,
            action=action,
        )
    )
    await session.flush()

    if action != "like":
        return None

    reverse = await session.scalar(
        select(Interaction).where(
            and_(
                Interaction.from_user_id == to_user_id,
                Interaction.to_user_id == from_user_id,
                Interaction.action == "like",
            )
        )
    )
    if not reverse:
        return None

    existing = await session.scalar(
        select(Match).where(
            or_(
                and_(Match.user1_id == from_user_id, Match.user2_id == to_user_id),
                and_(Match.user1_id == to_user_id, Match.user2_id == from_user_id),
            )
        )
    )
    if existing:
        return None

    match = Match(user1_id=from_user_id, user2_id=to_user_id)
    session.add(match)
    await session.flush()
    logger.info("New match: %s <-> %s", from_user_id, to_user_id)
    return match


# ── Cache warming (called by Celery tasks) ───────────────────────────────────

async def _warm_cache_for_user(user_id_str: str) -> None:
    """Load next feed batch into Redis for a single user."""
    from app.db.base import async_session

    uid = uuid.UUID(user_id_str)

    async with async_session() as session:
        candidates = await _get_candidate_ids(uid, session, limit=_BATCH_SIZE)

    if not candidates:
        logger.debug("warm_cache: no candidates for user=%s", user_id_str)
        return

    redis = Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )
    try:
        await cache_module.load_feed_cache(uid, candidates, redis)
        logger.info("Cache warmed for user=%s (%d profiles)", user_id_str, len(candidates))
    finally:
        await redis.aclose()


def warm_cache_sync(user_id_str: str) -> None:
    """Celery entry point: warm feed cache for one user."""
    asyncio.run(_warm_cache_for_user(user_id_str))


async def _warm_active_users() -> None:
    """Warm feed cache for users who interacted in the last 24 h."""
    from datetime import timedelta
    from sqlalchemy import select
    from app.db.base import async_session

    cutoff = __import__("datetime").datetime.utcnow() - timedelta(hours=24)

    async with async_session() as session:
        result = await session.scalars(
            select(distinct(Interaction.from_user_id))
            .where(Interaction.created_at >= cutoff)
            .limit(100)
        )
        active_ids = list(result.all())

    for uid in active_ids:
        try:
            await _warm_cache_for_user(str(uid))
        except Exception:
            logger.exception("warm_active: failed for user=%s", uid)

    logger.info("Cache warmed for %d active users", len(active_ids))


def warm_active_users_sync() -> None:
    """Celery entry point: warm caches for recently active users."""
    asyncio.run(_warm_active_users())


# ── Hot profiles cache ────────────────────────────────────────────────────────

async def _refresh_hot_profiles() -> None:
    """
    Rebuild the Redis sorted set 'hot_profiles' with top-100 users by final_score.
    Used by the feed to fast-rank candidates without hitting the DB.
    """
    from app.db.base import async_session

    async with async_session() as session:
        rows = list(
            (
                await session.execute(
                    select(Rating.user_id, Rating.final_score)
                    .order_by(Rating.final_score.desc())
                    .limit(100)
                )
            ).all()
        )

    if not rows:
        return

    redis = Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )
    try:
        pipe = redis.pipeline()
        pipe.delete(_HOT_PROFILES_KEY)
        for user_id, score in rows:
            pipe.zadd(_HOT_PROFILES_KEY, {str(user_id): float(score)})
        pipe.expire(_HOT_PROFILES_KEY, _HOT_PROFILES_TTL)
        await pipe.execute()
        logger.info("Hot profiles cache refreshed: %d entries", len(rows))
    finally:
        await redis.aclose()


def refresh_hot_profiles_sync() -> None:
    """Celery entry point: rebuild hot_profiles sorted set."""
    asyncio.run(_refresh_hot_profiles())
