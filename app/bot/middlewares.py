from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import async_session


class DbSessionMiddleware(BaseMiddleware):
    """Открывает сессию БД и передаёт её в data['session']."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with async_session() as session:
            async with session.begin():
                data["session"] = session
                return await handler(event, data)


class RedisMiddleware(BaseMiddleware):
    """Прокидывает общий Redis-клиент в data['redis']."""

    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["redis"] = self.redis
        return await handler(event, data)
