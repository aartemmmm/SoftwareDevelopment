"""
Fallback handler — перехватывает любые сообщения от незарегистрированных
пользователей вне FSM-состояний.

Убирает старую клавиатуру (ReplyKeyboardRemove) и напоминает нажать /start.
Включается ПОСЛЕДНИМ роутером, чтобы не перехватывать валидные команды.
"""
from __future__ import annotations

from aiogram import Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import Message, ReplyKeyboardRemove
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Profile, User

router = Router()


@router.message(StateFilter(default_state))
async def unregistered_fallback(message: Message, session: AsyncSession) -> None:
    tg_id = message.from_user.id if message.from_user else None
    if not tg_id:
        return

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if user:
        profile = await session.scalar(
            select(Profile).where(Profile.user_id == user.id)
        )
        if profile:
            # Зарегистрированный пользователь — не мешаем
            return

    # Незарегистрированный: убираем клавиатуру и подсказываем
    await message.answer(
        "Нажми /start чтобы зарегистрироваться 👆",
        reply_markup=ReplyKeyboardRemove(),
    )
