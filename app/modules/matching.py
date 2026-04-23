from __future__ import annotations

import logging
import uuid
from typing import Optional

from redis.asyncio import Redis
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Interaction, Match, Preferences, Profile, Rating, User
from app.modules import cache as cache_module

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10


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


async def get_next_profile_id(
    user_id: uuid.UUID,
    session: AsyncSession,
    redis: Redis,
) -> Optional[uuid.UUID]:
    cached_id = await cache_module.pop_from_feed(user_id, redis)
    if cached_id:
        return cached_id

    candidates = await _get_candidate_ids(user_id, session, limit=_BATCH_SIZE)
    if not candidates:
        return None

    if len(candidates) > 1:
        await cache_module.load_feed_cache(user_id, candidates[1:], redis)

    return candidates[0]


async def record_interaction(
    from_user_id: uuid.UUID,
    to_user_id: uuid.UUID,
    action: str,
    session: AsyncSession,
) -> Optional[Match]:
    interaction = Interaction(
        from_user_id=from_user_id,
        to_user_id=to_user_id,
        action=action,
    )
    session.add(interaction)
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
