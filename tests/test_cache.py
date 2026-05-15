"""
Unit tests for the Redis feed cache module.

Tests cover:
  - load_feed_cache: serialise and store IDs
  - pop_from_feed: FIFO ordering, list shrink, delete on empty
  - feed_size: count remaining IDs
  - clear_feed: explicit eviction
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, call

import pytest

from app.modules.cache import (
    clear_feed,
    feed_size,
    load_feed_cache,
    pop_from_feed,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_redis(initial_value: str | None = None) -> AsyncMock:
    """Redis mock that stores a single key in memory."""
    redis = AsyncMock()
    _store: dict[str, str | None] = {"key": initial_value}

    async def _get(key: str):
        return _store.get("key")

    async def _set(key: str, value: str, ex: int | None = None):
        _store["key"] = value

    async def _delete(key: str):
        _store["key"] = None

    redis.get.side_effect = _get
    redis.set.side_effect = _set
    redis.delete.side_effect = _delete
    return redis


# ── load_feed_cache ───────────────────────────────────────────────────────────

class TestLoadFeedCache:

    @pytest.mark.asyncio
    async def test_stores_serialised_ids(self):
        redis = AsyncMock()
        uid   = uuid.uuid4()
        ids   = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]

        await load_feed_cache(uid, ids, redis)

        redis.set.assert_called_once()
        _key, raw = redis.set.call_args[0][:2]
        stored = json.loads(raw)
        assert stored == [str(i) for i in ids]

    @pytest.mark.asyncio
    async def test_sets_ttl(self):
        redis = AsyncMock()
        await load_feed_cache(uuid.uuid4(), [uuid.uuid4()], redis)
        args, kwargs = redis.set.call_args
        # ex may come as keyword or 3rd positional arg
        ex = kwargs.get("ex") or (args[2] if len(args) > 2 else None)
        assert ex is not None and int(ex) > 0


# ── pop_from_feed ─────────────────────────────────────────────────────────────

class TestPopFromFeed:

    @pytest.mark.asyncio
    async def test_pop_returns_first_id(self):
        ids = [uuid.uuid4(), uuid.uuid4()]
        redis = _make_redis(json.dumps([str(i) for i in ids]))

        result = await pop_from_feed(uuid.uuid4(), redis)
        assert result == ids[0]

    @pytest.mark.asyncio
    async def test_pop_removes_first_updates_remainder(self):
        ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
        redis = _make_redis(json.dumps([str(i) for i in ids]))

        uid = uuid.uuid4()
        first  = await pop_from_feed(uid, redis)
        second = await pop_from_feed(uid, redis)

        assert first  == ids[0]
        assert second == ids[1]

    @pytest.mark.asyncio
    async def test_pop_last_item_deletes_key(self):
        ids = [uuid.uuid4()]
        redis = _make_redis(json.dumps([str(ids[0])]))

        result = await pop_from_feed(uuid.uuid4(), redis)

        assert result == ids[0]
        redis.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_pop_empty_cache_returns_none(self):
        redis = _make_redis(None)

        result = await pop_from_feed(uuid.uuid4(), redis)
        assert result is None

    @pytest.mark.asyncio
    async def test_pop_empty_list_returns_none(self):
        redis = _make_redis(json.dumps([]))

        result = await pop_from_feed(uuid.uuid4(), redis)
        assert result is None


# ── feed_size ─────────────────────────────────────────────────────────────────

class TestFeedSize:

    @pytest.mark.asyncio
    async def test_size_matches_number_of_ids(self):
        ids = [uuid.uuid4() for _ in range(5)]
        redis = _make_redis(json.dumps([str(i) for i in ids]))

        size = await feed_size(uuid.uuid4(), redis)
        assert size == 5

    @pytest.mark.asyncio
    async def test_empty_cache_returns_zero(self):
        redis = _make_redis(None)
        size = await feed_size(uuid.uuid4(), redis)
        assert size == 0


# ── clear_feed ────────────────────────────────────────────────────────────────

class TestClearFeed:

    @pytest.mark.asyncio
    async def test_clear_calls_delete(self):
        redis = AsyncMock()
        uid = uuid.uuid4()

        await clear_feed(uid, redis)
        redis.delete.assert_called_once()


# ── Integration: load → pop sequence ─────────────────────────────────────────

class TestLoadPopSequence:

    @pytest.mark.asyncio
    async def test_load_then_drain(self):
        """Load N profiles, pop all N; should end with None."""
        n   = 4
        ids = [uuid.uuid4() for _ in range(n)]
        uid = uuid.uuid4()

        # Use shared in-memory store
        store: dict = {}
        redis = AsyncMock()

        async def _get(key):
            return store.get(key)

        async def _set(key, value, ex=None):
            store[key] = value

        async def _delete(key):
            store.pop(key, None)

        redis.get.side_effect    = _get
        redis.set.side_effect    = _set
        redis.delete.side_effect = _delete

        await load_feed_cache(uid, ids, redis)

        popped = []
        for _ in range(n + 1):
            r = await pop_from_feed(uid, redis)
            popped.append(r)

        assert popped[:n] == ids
        assert popped[n] is None
