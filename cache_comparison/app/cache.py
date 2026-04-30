import json
import os
from typing import Optional

import redis.asyncio as aioredis

_redis: Optional[aioredis.Redis] = None

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))


async def init_cache() -> None:
    global _redis
    _redis = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)


async def close_cache() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None


def get_redis() -> aioredis.Redis:
    return _redis


async def cache_get(key: str) -> Optional[dict]:
    raw = await _redis.get(key)
    return json.loads(raw) if raw else None


async def cache_set(key: str, value: dict, ttl: int = CACHE_TTL) -> None:
    await _redis.setex(key, ttl, json.dumps(value))


async def cache_delete(key: str) -> None:
    await _redis.delete(key)


async def flush_product_cache() -> None:
    """Delete all product:* and write_back:* keys (used between test runs)."""
    keys = await _redis.keys("product:*")
    wb_keys = await _redis.keys("write_back:*")
    all_keys = keys + wb_keys
    if all_keys:
        await _redis.delete(*all_keys)
