"""
Cache Module — кэширование предварительно ранжированной ленты в Redis.

Алгоритм сессии:
  1. При открытии ленты: получаем первый профиль через полный путь ранжирования,
     одновременно подгружаем ещё 9 анкет в Redis.
  2. Последующие анкеты берём из кэша (O(1)).
  3. На последней анкете из 10 круг повторяется.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from redis.asyncio import Redis

_FEED_KEY = "feed:{uid}"
_FEED_TTL = 3600  # 1 час


def _key(user_id: uuid.UUID) -> str:
    return _FEED_KEY.format(uid=user_id)


async def feed_size(user_id: uuid.UUID, redis: Redis) -> int:
    raw = await redis.get(_key(user_id))
    if not raw:
        return 0
    return len(json.loads(raw))


async def load_feed_cache(
    user_id: uuid.UUID, profile_ids: list[uuid.UUID], redis: Redis
) -> None:
    """Сохранить список ID анкет в Redis-кэш."""
    await redis.set(
        _key(user_id),
        json.dumps([str(pid) for pid in profile_ids]),
        ex=_FEED_TTL,
    )


async def pop_from_feed(user_id: uuid.UUID, redis: Redis) -> Optional[uuid.UUID]:
    """
    Извлечь следующий ID анкеты из кэша (FIFO).
    Возвращает None если кэш пуст.
    """
    raw = await redis.get(_key(user_id))
    if not raw:
        return None

    ids: list[str] = json.loads(raw)
    if not ids:
        await redis.delete(_key(user_id))
        return None

    next_id = ids.pop(0)

    if ids:
        await redis.set(_key(user_id), json.dumps(ids), ex=_FEED_TTL)
    else:
        await redis.delete(_key(user_id))

    return uuid.UUID(next_id)


async def clear_feed(user_id: uuid.UUID, redis: Redis) -> None:
    await redis.delete(_key(user_id))
