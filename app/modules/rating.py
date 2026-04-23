from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session
from app.db.models import Interaction, Match, Photo, Profile, Rating

logger = logging.getLogger(__name__)

_PRIMARY_WEIGHT = 0.3
_BEHAVIOR_WEIGHT = 0.7


async def calculate_primary_score(user_id: uuid.UUID, session: AsyncSession) -> float:
    score = 0.0

    profile = await session.scalar(
        select(Profile).where(Profile.user_id == user_id)
    )
    if profile:
        score += 2.0   
        score += 2.0 
        score += 2.0
        if profile.bio:
            score += 2.0  
        if profile.city:
            score += 2.0 

    photo_count: int = await session.scalar(
        select(func.count(Photo.id)).where(Photo.user_id == user_id)
    ) or 0

    if photo_count == 1:
        score += 1.0   # +0.83
    elif photo_count >= 2:
        score += 2.0   # +1.67

    max_possible = 12.0
    return round(min(score / max_possible * 10, 10.0), 2)


async def calculate_behavior_score(user_id: uuid.UUID, session: AsyncSession) -> float:
    likes_received: int = await session.scalar(
        select(func.count(Interaction.id))
        .where(Interaction.to_user_id == user_id)
        .where(Interaction.action == "like")
    ) or 0

    total_received: int = await session.scalar(
        select(func.count(Interaction.id)).where(Interaction.to_user_id == user_id)
    ) or 0

    matches_count: int = await session.scalar(
        select(func.count(Match.id)).where(
            or_(Match.user1_id == user_id, Match.user2_id == user_id)
        )
    ) or 0

    like_score = min(likes_received / 50.0, 1.0) * 4.0

    ratio_score = (likes_received / total_received * 3.0) if total_received > 0 else 0.0

    match_score = (
        min(matches_count / likes_received, 1.0) * 3.0 if likes_received > 0 else 0.0
    )

    return round(min(like_score + ratio_score + match_score, 10.0), 2)


async def recalculate_rating(user_id: uuid.UUID, session: AsyncSession) -> Rating:
    primary = await calculate_primary_score(user_id, session)
    behavioral = await calculate_behavior_score(user_id, session)

    total_received: int = await session.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.to_user_id == user_id
        )
    ) or 0

    if total_received == 0:
        final = primary
    else:
        final = round(primary * _PRIMARY_WEIGHT + behavioral * _BEHAVIOR_WEIGHT, 2)

    rating = await session.scalar(
        select(Rating).where(Rating.user_id == user_id)
    )
    if rating:
        rating.primary_score = primary
        rating.behavior_score = behavioral
        rating.final_score = final
    else:
        rating = Rating(
            user_id=user_id,
            primary_score=primary,
            behavior_score=behavioral,
            final_score=final,
        )
        session.add(rating)

    await session.flush()
    logger.debug(
        "Rating updated user=%s primary=%.2f behavior=%.2f final=%.2f",
        user_id,
        primary,
        behavioral,
        final,
    )
    return rating



async def _recalculate_all() -> None:
    from sqlalchemy import select as _select
    from app.db.models import User

    async with async_session() as session:
        async with session.begin():
            user_ids = list(await session.scalars(_select(User.id)))

    for uid in user_ids:
        try:
            async with async_session() as session:
                async with session.begin():
                    await recalculate_rating(uid, session)
        except Exception:
            logger.exception("Failed to recalculate rating for user=%s", uid)


async def _recalculate_one(user_id_str: str) -> None:
    uid = uuid.UUID(user_id_str)
    async with async_session() as session:
        async with session.begin():
            await recalculate_rating(uid, session)


def recalculate_all_sync() -> None:
    """Точка входа для Celery-задачи периодического пересчёта."""
    asyncio.run(_recalculate_all())


def recalculate_one_sync(user_id_str: str) -> None:
    """Точка входа для Celery-задачи пересчёта одного пользователя."""
    asyncio.run(_recalculate_one(user_id_str))
