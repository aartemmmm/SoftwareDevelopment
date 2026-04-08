from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from users_service.models import Profile, User, async_session

router = Router()


class RegStates(StatesGroup):
    name = State()
    age = State()
    gender = State()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    async with async_session() as session:
        user_result = await session.execute(
            select(User).where(User.telegram_id == message.from_user.id)
        )
        user = user_result.scalar_one_or_none()

        profile = None
        if user:
            profile_result = await session.execute(
                select(Profile).where(Profile.user_id == user.id)
            )
            profile = profile_result.scalar_one_or_none()

        if user and profile:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="Обновить анкету", callback_data="update"),
                    InlineKeyboardButton(text="Оставить как есть", callback_data="keep"),
                ]
            ])
            gender_label = "Мужской" if profile.gender == "male" else "Женский"
            await message.answer(
                f"Привет, *{profile.name}*! Ты уже зарегистрирован.\n"
                f"Возраст: {profile.age}, пол: {gender_label}\n\n"
                f"Хочешь обновить анкету?",
                reply_markup=kb,
                parse_mode="Markdown",
            )
            return

    await message.answer("Привет! Давай создадим твою анкету.\n\nКак тебя зовут?")
    await state.set_state(RegStates.name)


@router.callback_query(F.data == "update")
async def cb_update(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.answer("Введи новое имя:")
    await callback.answer()
    await state.set_state(RegStates.name)


@router.callback_query(F.data == "keep")
async def cb_keep(callback: CallbackQuery) -> None:
    await callback.message.answer("Хорошо, анкета не изменена.")
    await callback.answer()


@router.message(RegStates.name)
async def reg_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip())
    await message.answer("Сколько тебе лет?")
    await state.set_state(RegStates.age)


@router.message(RegStates.age)
async def reg_age(message: Message, state: FSMContext) -> None:
    if not message.text.isdigit() or not (18 <= int(message.text) <= 99):
        await message.answer("Введи корректный возраст (число от 18 до 99):")
        return

    await state.update_data(age=int(message.text))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Мужской", callback_data="male"),
            InlineKeyboardButton(text="Женский", callback_data="female"),
        ]
    ])
    await message.answer("Выбери свой пол:", reply_markup=kb)
    await state.set_state(RegStates.gender)


@router.callback_query(RegStates.gender)
async def reg_gender(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    gender = callback.data

    async with async_session() as session:
        async with session.begin():
            user_result = await session.execute(
                select(User).where(User.telegram_id == callback.from_user.id)
            )
            user = user_result.scalar_one_or_none()

            if user is None:
                user = User(telegram_id=callback.from_user.id)
                session.add(user)
                await session.flush()
                session.add(Profile(
                    user_id=user.id,
                    name=data["name"],
                    age=data["age"],
                    gender=gender,
                ))
            else:
                profile_result = await session.execute(
                    select(Profile).where(Profile.user_id == user.id)
                )
                profile = profile_result.scalar_one_or_none()
                if profile:
                    profile.name = data["name"]
                    profile.age = data["age"]
                    profile.gender = gender
                else:
                    session.add(Profile(
                        user_id=user.id,
                        name=data["name"],
                        age=data["age"],
                        gender=gender,
                    ))

    await state.clear()
    await callback.answer()
    await callback.message.answer("Анкета создана! Добро пожаловать.")
