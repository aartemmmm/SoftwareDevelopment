"""
Unit tests for matchmaking logic.

Tests cover:
  - record_interaction: like / skip storage, mutual-like detection, match creation
  - No duplicate Match records on repeated mutual likes
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.matching import record_interaction


class TestRecordInteraction:

    @pytest.mark.asyncio
    async def test_skip_does_not_create_match(self):
        """A skip interaction is stored but never creates a Match."""
        session = AsyncMock()
        session.flush = AsyncMock()
        # scalar for reverse-like check — not reached for skip
        session.scalar.return_value = None

        result = await record_interaction(
            uuid.uuid4(), uuid.uuid4(), "skip", session
        )

        assert result is None
        session.add.assert_called_once()  # only the Interaction row

    @pytest.mark.asyncio
    async def test_one_way_like_no_match(self):
        """Like without a reverse like → no Match created."""
        session = AsyncMock()
        session.flush = AsyncMock()
        # No reverse interaction found
        session.scalar.return_value = None

        result = await record_interaction(
            uuid.uuid4(), uuid.uuid4(), "like", session
        )

        assert result is None
        # Only the Interaction row is added
        assert session.add.call_count == 1

    @pytest.mark.asyncio
    async def test_mutual_like_creates_match(self):
        """Both users liked each other → Match object returned and stored."""
        session = AsyncMock()
        session.flush = AsyncMock()

        reverse_interaction = MagicMock()  # non-None → reverse like exists

        # scalar calls: (1) reverse interaction check, (2) existing match check
        session.scalar.side_effect = [reverse_interaction, None]

        u1 = uuid.uuid4()
        u2 = uuid.uuid4()
        result = await record_interaction(u1, u2, "like", session)

        assert result is not None
        assert result.user1_id == u1
        assert result.user2_id == u2
        # add called twice: Interaction + Match
        assert session.add.call_count == 2

    @pytest.mark.asyncio
    async def test_no_duplicate_match(self):
        """If a Match already exists for the pair, return None (idempotent)."""
        session = AsyncMock()
        session.flush = AsyncMock()

        reverse_interaction = MagicMock()
        existing_match      = MagicMock()  # already stored

        session.scalar.side_effect = [reverse_interaction, existing_match]

        result = await record_interaction(
            uuid.uuid4(), uuid.uuid4(), "like", session
        )

        assert result is None
        # Only the Interaction row is added (no second Match)
        assert session.add.call_count == 1
