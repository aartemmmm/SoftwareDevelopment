import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from users_service.handlers import router
from users_service.models import Base, engine

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


async def main() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logging.info("Таблицы готовы")

    bot = Bot(token=os.environ["BOT_TOKEN"])
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logging.info("Бот запущен")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
