"""
Точка входа приложения.

Запуск:
    python main.py

Celery worker (отдельный процесс):
    celery -A celery_app worker -l info

Celery beat (планировщик):
    celery -A celery_app beat -l info
"""
import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault, MenuButtonCommands
from dotenv import load_dotenv
from redis.asyncio import Redis

from app.bot.handlers import fallback, feed, profile, registration
from app.bot.middlewares import DbSessionMiddleware, RedisMiddleware
from app.db.base import engine
from app.db.models import Base

load_dotenv(Path(__file__).parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    # Создаём таблицы в БД
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # Redis клиент
    redis = Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )

    bot = Bot(token=os.environ["BOT_TOKEN"])
    dp = Dispatcher(storage=MemoryStorage())

    # Middlewares (порядок важен: сначала Redis, потом DB)
    dp.update.middleware(RedisMiddleware(redis))
    dp.update.middleware(DbSessionMiddleware())

    # Роутеры (порядок важен: fallback всегда последний)
    dp.include_router(registration.router)
    dp.include_router(profile.router)
    dp.include_router(feed.router)
    dp.include_router(fallback.router)

    # Кнопка Menu и список команд в интерфейсе Telegram
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Начать / перезапустить бота"),
        ],
        scope=BotCommandScopeDefault(),
    )
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    logger.info("Bot commands set")

    logger.info("Bot started")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
        await engine.dispose()
        await redis.aclose()
        logger.info("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
