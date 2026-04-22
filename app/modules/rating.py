"""
Rating Module — трёхуровневая система рейтинга.

Уровень 1 (primary_score):   полнота анкеты + количество фото
Уровень 2 (behavior_score):  лайки, соотношение лайков/пропусков, частота мэтчей
Уровень 3 (final_score):     взвешенная комбинация (30% primary + 70% behavioral)
"""
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
    """
    Уровень 1 — первичный рейтинг.
    Учитывает полноту анкеты (name, age, gender, bio, city) и количество фото.
    Нормализован до шкалы 0–10.

    Базовые обязательные поля (name+age+gender) дают ровно 5.0 —
    это стартовый рейтинг любой новой анкеты.
    Дополнительные поля и фото поднимают его до 10.0.
    """
    score = 0.0

    profile = await session.scalar(
        select(Profile).where(Profile.user_id == user_id)
    )
    if profile:
        score += 2.0  # name   ┐
        score += 2.0  # age    ├─ base = 6/12 → 5.0
        score += 2.0  # gender ┘
        if profile.bio:
            score += 2.0   # +1.67 итого
        if profile.city:
            score += 2.0   # +1.67 итого

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
    """
    Уровень 2 — поведенческий рейтинг.
    Учитывает:
      - количество лайков анкеты (max 4 балла)
      - соотношение лайков к пропускам  (max 3 балла)
      - частоту взаимных мэтчей         (max 3 балла)
    Результат: 0–10.
    """
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

    # Лайки: логарифмическое насыщение при ~50 лайках
    like_score = min(likes_received / 50.0, 1.0) * 4.0

    # Соотношение лайков/пропусков
    ratio_score = (likes_received / total_received * 3.0) if total_received > 0 else 0.0

    # Частота мэтчей относительно лайков
    match_score = (
        min(matches_count / likes_received, 1.0) * 3.0 if likes_received > 0 else 0.0
    )

    return round(min(like_score + ratio_score + match_score, 10.0), 2)


async def recalculate_rating(user_id: uuid.UUID, session: AsyncSession) -> Rating:
    """
    Уровень 3 — пересчитывает все три уровня и сохраняет в БД.

    Cold-start правило: если пользователь ещё не получал никаких реакций,
    поведенческих данных нет — final_score = primary_score.
    Это гарантирует стартовый рейтинг 5.0 для минимально заполненной анкеты.
    Как только появляются первые реакции, начинает работать взвешенная формула.
    """
    primary = await calculate_primary_score(user_id, session)
    behavioral = await calculate_behavior_score(user_id, session)

    total_received: int = await session.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.to_user_id == user_id
        )
    ) or 0

    if total_received == 0:
        # Нет поведенческих данных — рейтинг определяется только анкетой
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


# ---------------------------------------------------------------------------
# Функции для Celery-задач (синхронная обёртка через asyncio.run)
# ---------------------------------------------------------------------------

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
