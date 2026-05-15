"""
Rating module — three-level scoring system.

┌─ Level 1 (level1_score) — Profile completeness (static quality) ──────────┐
│  name + age + gender        → base 6 pts                                   │
│  bio                        → +2 pts                                       │
│  city                       → +2 pts                                       │
│  interests                  → +2 pts                                       │
│  photo × 1 / × ≥2           → +1 / +2 pts                                 │
│  max raw = 14 → normalised 0–10                                             │
└────────────────────────────────────────────────────────────────────────────┘

┌─ Level 2 (level2_score) — Behavioral engagement (dynamic) ─────────────────┐
│  likes received (up to 50)         → 0–4 pts                               │
│  like-to-view ratio                → 0–3 pts                               │
│  like-to-match conversion          → 0–3 pts                               │
│  temporal activity (recency)       → 0–2 pts                               │
│  max = 12 → capped at 10                                                    │
└────────────────────────────────────────────────────────────────────────────┘

┌─ Level 3 (final_score) — Combined with additional factors ─────────────────┐
│  base = 0.3 × L1 + 0.7 × L2                                                │
│  × freshness_multiplier (new profiles get up to +15% boost)                │
│  capped at 10.0                                                             │
└────────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session
from app.db.models import Interaction, Match, Photo, Profile, Rating, User

logger = logging.getLogger(__name__)

_L1_WEIGHT = 0.3
_L2_WEIGHT = 0.7


# ── Level 1: Profile completeness ────────────────────────────────────────────

async def calculate_level1_score(user_id: uuid.UUID, session: AsyncSession) -> float:
    """
    Static quality score based on profile completeness.
    Signals: name/age/gender, bio, city, interests, photos.
    """
    score = 0.0

    profile = await session.scalar(
        select(Profile).where(Profile.user_id == user_id)
    )
    if profile:
        score += 2.0   # name
        score += 2.0   # age
        score += 2.0   # gender
        if profile.bio:
            score += 2.0
        if profile.city:
            score += 2.0
        if profile.interests:
            score += 2.0   # interests / hobbies

    photo_count: int = await session.scalar(
        select(func.count(Photo.id)).where(Photo.user_id == user_id)
    ) or 0

    if photo_count == 1:
        score += 1.0
    elif photo_count >= 2:
        score += 2.0

    max_possible = 14.0   # 6 (base) + 2 + 2 + 2 + 2 (photos)
    return round(min(score / max_possible * 10, 10.0), 2)


# ── Level 2: Behavioral engagement ───────────────────────────────────────────

async def calculate_level2_score(user_id: uuid.UUID, session: AsyncSession) -> float:
    """
    Dynamic score based on received interactions and temporal activity.
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

    # Sub-score A: raw like volume (0–4 pts, saturates at 50 likes)
    like_volume_score = min(likes_received / 50.0, 1.0) * 4.0

    # Sub-score B: like-to-view ratio (0–3 pts)
    ratio_score = (likes_received / total_received * 3.0) if total_received > 0 else 0.0

    # Sub-score C: like-to-match conversion (0–3 pts)
    match_score = (
        min(matches_count / likes_received, 1.0) * 3.0 if likes_received > 0 else 0.0
    )

    # Sub-score D: temporal activity — recency of last interaction sent (0–2 pts)
    last_sent: datetime | None = await session.scalar(
        select(func.max(Interaction.created_at))
        .where(Interaction.from_user_id == user_id)
    )
    if last_sent is None:
        temporal_score = 0.0
    else:
        days_idle = (datetime.utcnow() - last_sent).days
        if days_idle <= 7:
            temporal_score = 2.0   # active this week
        elif days_idle <= 30:
            temporal_score = 1.0   # active this month
        else:
            temporal_score = 0.0   # dormant

    raw = like_volume_score + ratio_score + match_score + temporal_score
    return round(min(raw, 10.0), 2)


# ── Level 3: Combined with freshness multiplier ───────────────────────────────

async def recalculate_rating(user_id: uuid.UUID, session: AsyncSession) -> Rating:
    """
    Compute final_score = base × freshness_multiplier, where:
      base = L1 × 0.3 + L2 × 0.7   (or just L1 for new users)
      freshness_multiplier — boosts profiles of recently registered users
        ≤ 7 days old  →  × 1.15
        ≤ 30 days old →  × 1.05
        older         →  × 1.00
    """
    level1 = await calculate_level1_score(user_id, session)
    level2 = await calculate_level2_score(user_id, session)

    total_received: int = await session.scalar(
        select(func.count(Interaction.id)).where(
            Interaction.to_user_id == user_id
        )
    ) or 0

    # Base score
    if total_received == 0:
        base_score = level1   # no behavioral data yet → show new profiles
    else:
        base_score = round(level1 * _L1_WEIGHT + level2 * _L2_WEIGHT, 2)

    # Freshness multiplier (Level 3 additional factor)
    user = await session.scalar(select(User).where(User.id == user_id))
    if user and user.created_at:
        account_age_days = (datetime.utcnow() - user.created_at).days
        if account_age_days <= 7:
            freshness = 1.15
        elif account_age_days <= 30:
            freshness = 1.05
        else:
            freshness = 1.0
    else:
        freshness = 1.0

    final = round(min(base_score * freshness, 10.0), 2)

    rating = await session.scalar(
        select(Rating).where(Rating.user_id == user_id)
    )
    if rating:
        rating.level1_score = level1
        rating.level2_score = level2
        rating.final_score  = final
    else:
        rating = Rating(
            user_id=user_id,
            level1_score=level1,
            level2_score=level2,
            final_score=final,
        )
        session.add(rating)

    await session.flush()
    logger.debug(
        "Rating user=%s L1=%.2f L2=%.2f fresh=%.2f final=%.2f",
        user_id, level1, level2, freshness, final,
    )
    return rating


# ── Bulk / one-shot helpers (sync wrappers for Celery) ───────────────────────

async def _recalculate_all() -> None:
    from app.db.models import User as _User

    async with async_session() as session:
        async with session.begin():
            user_ids = list(await session.scalars(select(_User.id)))

    processed = 0
    for uid in user_ids:
        try:
            async with async_session() as session:
                async with session.begin():
                    await recalculate_rating(uid, session)
            processed += 1
        except Exception:
            logger.exception("Failed to recalculate rating for user=%s", uid)

    logger.info("Bulk recalculation done: %d/%d", processed, len(user_ids))


async def _recalculate_one(user_id_str: str) -> None:
    uid = uuid.UUID(user_id_str)
    async with async_session() as session:
        async with session.begin():
            await recalculate_rating(uid, session)


def recalculate_all_sync() -> None:
    asyncio.run(_recalculate_all())


def recalculate_one_sync(user_id_str: str) -> None:
    asyncio.run(_recalculate_one(user_id_str))


# Backwards-compatible aliases
calculate_primary_score  = calculate_level1_score
calculate_behavior_score = calculate_level2_score
