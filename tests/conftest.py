"""
Shared pytest fixtures.

DB and Redis modules are mocked at the sys.modules level so tests
run without a live PostgreSQL / Redis connection.
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── Stub out db.base before any test module imports it ───────────────────────
# This prevents create_async_engine from being called (which needs asyncpg).

_mock_engine  = MagicMock()
_mock_session = MagicMock()

_db_base_stub = MagicMock()
_db_base_stub.engine        = _mock_engine
_db_base_stub.async_session = _mock_session

sys.modules.setdefault("app.db.base", _db_base_stub)

# Also stub dotenv so tests don't require python-dotenv in the test venv
if "dotenv" not in sys.modules:
    _dotenv_stub = MagicMock()
    _dotenv_stub.load_dotenv = lambda *a, **kw: None
    sys.modules["dotenv"] = _dotenv_stub


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def sample_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def mock_session() -> AsyncMock:
    """Async SQLAlchemy session mock."""
    return AsyncMock()


@pytest.fixture
def mock_redis() -> AsyncMock:
    """
    Async Redis mock with an in-memory key-value store.
    Supports: get, set, delete.
    """
    redis  = AsyncMock()
    _store: dict[str, Any] = {}

    async def _get(key: str):
        return _store.get(key)

    async def _set(key: str, value: Any, ex: int | None = None):
        _store[key] = value

    async def _delete(*keys: str):
        for k in keys:
            _store.pop(k, None)

    redis.get.side_effect    = _get
    redis.set.side_effect    = _set
    redis.delete.side_effect = _delete
    redis._store = _store

    return redis
