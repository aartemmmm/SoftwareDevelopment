"""
Unit tests for the three-level rating system.

Tests cover:
  - Level 1 (calculate_level1_score): profile completeness scoring (max_raw=14)
  - Level 2 (calculate_level2_score): behavioral + temporal activity scoring
  - Final score: weighted blend + freshness multiplier logic
  - recalculate_rating: full pipeline (create vs update)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.rating import (
    calculate_level1_score,
    calculate_level2_score,
    recalculate_rating,
)


# ── Level 1: Profile completeness ────────────────────────────────────────────

class TestLevel1Score:

    @pytest.mark.asyncio
    async def test_full_profile_with_photos_scores_ten(self):
        """Complete profile (bio + city + interests) with ≥2 photos → score = 10.0."""
        session = AsyncMock()

        profile = MagicMock()
        profile.bio       = "Some bio text"
        profile.city      = "Moscow"
        profile.interests = "hiking, movies"

        session.scalar.side_effect = [profile, 3]
        score = await calculate_level1_score(uuid.uuid4(), session)
        assert score == 10.0

    @pytest.mark.asyncio
    async def test_profile_no_optional_fields(self):
        """Base fields only (name/age/gender), no bio/city/interests/photos → 6/14*10 ≈ 4.29."""
        session = AsyncMock()

        profile = MagicMock()
        profile.bio       = None
        profile.city      = None
        profile.interests = None

        session.scalar.side_effect = [profile, 0]

        score = await calculate_level1_score(uuid.uuid4(), session)
        assert round(score, 2) == round(6 / 14 * 10, 2)

    @pytest.mark.asyncio
    async def test_profile_one_photo(self):
        """One photo (+1 raw) → 7/14*10 = 5.0."""
        session = AsyncMock()

        profile = MagicMock()
        profile.bio       = None
        profile.city      = None
        profile.interests = None

        session.scalar.side_effect = [profile, 1]

        score = await calculate_level1_score(uuid.uuid4(), session)
        assert score == 5.0

    @pytest.mark.asyncio
    async def test_no_profile_returns_zero(self):
        """User without profile → score 0.0."""
        session = AsyncMock()
        session.scalar.side_effect = [None, 0]

        score = await calculate_level1_score(uuid.uuid4(), session)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_capped_at_ten(self):
        """Score can never exceed 10.0."""
        session = AsyncMock()

        profile = MagicMock()
        profile.bio       = "x"
        profile.city      = "y"
        profile.interests = "z"

        session.scalar.side_effect = [profile, 100]

        score = await calculate_level1_score(uuid.uuid4(), session)
        assert score <= 10.0

    @pytest.mark.asyncio
    async def test_interests_adds_score(self):
        """Profile with interests scores higher than without."""
        session_with    = AsyncMock()
        session_without = AsyncMock()

        p_with            = MagicMock()
        p_with.bio        = None
        p_with.city       = None
        p_with.interests  = "coding, gaming"

        p_without           = MagicMock()
        p_without.bio       = None
        p_without.city      = None
        p_without.interests = None

        session_with.scalar.side_effect    = [p_with,    0]
        session_without.scalar.side_effect = [p_without, 0]

        uid = uuid.uuid4()
        score_with    = await calculate_level1_score(uid, session_with)
        score_without = await calculate_level1_score(uid, session_without)

        assert score_with > score_without


# ── Level 2: Behavioral engagement ───────────────────────────────────────────

class TestLevel2Score:

    @pytest.mark.asyncio
    async def test_no_interactions_returns_zero(self):
        """Brand-new user with no interactions → L2 = 0.0."""
        session = AsyncMock()
        # likes_received, total_received, matches, last_sent
        session.scalar.side_effect = [0, 0, 0, None]

        score = await calculate_level2_score(uuid.uuid4(), session)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_many_likes_boosts_score(self):
        """50 likes, 50 views, 0 matches, inactive → 4.0 + 3.0 = 7.0."""
        session = AsyncMock()
        session.scalar.side_effect = [50, 50, 0, None]

        score = await calculate_level2_score(uuid.uuid4(), session)
        assert score == pytest.approx(7.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_active_this_week_adds_temporal_bonus(self):
        """User active within 7 days gets +2 temporal bonus."""
        session = AsyncMock()
        recent = datetime.utcnow() - timedelta(days=3)
        session.scalar.side_effect = [0, 0, 0, recent]

        score = await calculate_level2_score(uuid.uuid4(), session)
        assert score == pytest.approx(2.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_active_this_month_adds_small_bonus(self):
        """User active within 30 days gets +1 temporal bonus."""
        session = AsyncMock()
        recent = datetime.utcnow() - timedelta(days=15)
        session.scalar.side_effect = [0, 0, 0, recent]

        score = await calculate_level2_score(uuid.uuid4(), session)
        assert score == pytest.approx(1.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_dormant_user_no_temporal_bonus(self):
        """User inactive for 60+ days → temporal bonus = 0."""
        session = AsyncMock()
        old = datetime.utcnow() - timedelta(days=60)
        session.scalar.side_effect = [0, 0, 0, old]

        score = await calculate_level2_score(uuid.uuid4(), session)
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_score_capped_at_ten(self):
        """L2 can never exceed 10."""
        session = AsyncMock()
        recent = datetime.utcnow() - timedelta(days=1)
        session.scalar.side_effect = [1000, 1000, 1000, recent]

        score = await calculate_level2_score(uuid.uuid4(), session)
        assert score <= 10.0


# ── Final rating: recalculate_rating ─────────────────────────────────────────

class TestRecalculateRating:

    @pytest.mark.asyncio
    async def test_new_user_final_equals_level1(self):
        """
        User with 0 received interactions → final_score = level1_score × freshness.
        """
        session = AsyncMock()

        profile_mock = MagicMock(bio="x", city="y", interests="z")
        user_mock    = MagicMock()
        user_mock.created_at = datetime.utcnow() - timedelta(days=200)  # old, no boost

        session.scalar.side_effect = [
            profile_mock, 2,    # L1 scalars: profile + photo_count
            0, 0, 0, None,       # L2 scalars: likes, total, matches, last_sent
            0,                   # gate: total_received = 0 → final = L1
            user_mock,           # freshness: User row
            None,                # no existing Rating row
        ]
        session.flush = AsyncMock()

        rating = await recalculate_rating(uuid.uuid4(), session)

        # freshness = 1.0 (old user), final = L1 * 1.0 = L1
        assert rating.final_score == pytest.approx(rating.level1_score, abs=0.01)
        session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_new_account_gets_freshness_boost(self):
        """User registered ≤7 days ago → final_score > base_score (×1.15)."""
        session = AsyncMock()

        profile_mock = MagicMock(bio=None, city=None, interests=None)
        fresh_user   = MagicMock()
        fresh_user.created_at = datetime.utcnow() - timedelta(days=2)  # brand new

        existing_rating = MagicMock()

        session.scalar.side_effect = [
            profile_mock, 0,    # L1
            0, 0, 0, None,       # L2
            0,                   # gate: new user
            fresh_user,          # freshness lookup
            existing_rating,     # existing Rating row
        ]
        session.flush = AsyncMock()

        await recalculate_rating(uuid.uuid4(), session)

        # level1 = 6/14*10 ≈ 4.29, × 1.15 ≈ 4.93
        assert existing_rating.final_score > existing_rating.level1_score

    @pytest.mark.asyncio
    async def test_established_user_uses_weighted_blend(self):
        """User with interactions → final = 0.3×L1 + 0.7×L2 (no boost for old user)."""
        session = AsyncMock()

        profile_mock = MagicMock(bio="x", city="y", interests="z")
        old_user     = MagicMock()
        old_user.created_at = datetime.utcnow() - timedelta(days=200)

        existing_rating = MagicMock()

        recent = datetime.utcnow() - timedelta(days=1)
        session.scalar.side_effect = [
            profile_mock, 2,    # L1 → 10.0
            50, 50, 50, recent,  # L2 → capped at 10.0
            50,                  # gate: has interactions → use blend
            old_user,
            existing_rating,
        ]
        session.flush = AsyncMock()

        await recalculate_rating(uuid.uuid4(), session)

        # blend: 10*0.3 + 10*0.7 = 10.0, × 1.0 = 10.0
        assert existing_rating.final_score == pytest.approx(10.0, abs=0.05)

    @pytest.mark.asyncio
    async def test_updates_existing_rating_row(self):
        """Existing Rating row is updated in-place, not duplicated."""
        session = AsyncMock()

        profile_mock    = MagicMock(bio=None, city=None, interests=None)
        old_user        = MagicMock()
        old_user.created_at = datetime.utcnow() - timedelta(days=200)
        existing_rating = MagicMock()

        session.scalar.side_effect = [
            profile_mock, 0,
            0, 0, 0, None,
            0,
            old_user,
            existing_rating,
        ]
        session.flush = AsyncMock()

        await recalculate_rating(uuid.uuid4(), session)

        session.add.assert_not_called()
