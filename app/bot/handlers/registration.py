from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    gender_kb,
    main_menu_kb,
    preferred_gender_kb,
    skip_kb,
)
from app.db.models import Photo, Preferences, Profile, Rating, User
from app.modules import rating as rating_module
from app.modules import storage

logger = logging.getLogger(__name__)
router = Router()


class RegStates(StatesGroup):
    name = State()
    age = State()
    gender = State()
    city = State()
    bio = State()
    pref_gender = State()
    pref_min_age = State()
    pref_max_age = State()
    photo = State()


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, session: AsyncSession) -> None:
    # Сбрасываем любое зависшее FSM-состояние (актуально после вайпа БД)
    await state.clear()

    tg_id = message.from_user.id if message.from_user else None
    if tg_id is None:
        return

    tg_username = message.from_user.username if message.from_user else None

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))

    if user:
        # Обновляем username если он изменился
        if user.username != tg_username:
            user.username = tg_username

        profile = await session.scalar(
            select(Profile).where(Profile.user_id == user.id)
        )
        if profile:
            gender_label = "Мужской" if profile.gender == "male" else "Женский"
            bio_text = f"\n📝 {profile.bio}" if profile.bio else ""
            city_text = f"\n🏙 {profile.city}" if profile.city else ""
            await message.answer(
                f"Привет, *{profile.name}*! Ты уже зарегистрирован.\n"
                f"🎂 Возраст: {profile.age} | ⚧ {gender_label}"
                f"{city_text}{bio_text}\n\n"
                f"Используй меню ниже:",
                parse_mode="Markdown",
                reply_markup=main_menu_kb(),
            )
            return

    # Новый пользователь — убираем старую клавиатуру и сразу начинаем регистрацию
    await state.update_data(tg_username=tg_username)
    await message.answer(
        "👋 Привет! Я *forpeep* — бот для знакомств.\n\nКак тебя зовут?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    await state.set_state(RegStates.name)


# ---------------------------------------------------------------------------
# name
# ---------------------------------------------------------------------------

@router.message(RegStates.name)
async def reg_name(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 100:
        await message.answer("Введи имя (до 100 символов):")
        return
    await state.update_data(name=text)
    await message.answer("🎂 Сколько тебе лет?")
    await state.set_state(RegStates.age)


# ---------------------------------------------------------------------------
# age
# ---------------------------------------------------------------------------

@router.message(RegStates.age)
async def reg_age(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (18 <= int(text) <= 99):
        await message.answer("Введи корректный возраст (от 18 до 99):")
        return
    await state.update_data(age=int(text))
    await message.answer("⚧ Выбери свой пол:", reply_markup=gender_kb())
    await state.set_state(RegStates.gender)


# ---------------------------------------------------------------------------
# gender (callback)
# ---------------------------------------------------------------------------

@router.callback_query(RegStates.gender, F.data.startswith("gender:"))
async def reg_gender(callback: CallbackQuery, state: FSMContext) -> None:
    gender = (callback.data or "").split(":")[1]
    await state.update_data(gender=gender)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "🏙 В каком городе ты живёшь?",
            reply_markup=skip_kb(),
        )
    await state.set_state(RegStates.city)


# ---------------------------------------------------------------------------
# city
# ---------------------------------------------------------------------------

@router.message(RegStates.city)
async def reg_city(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if len(text) > 100:
        await message.answer("Слишком длинно, до 100 символов:")
        return
    await state.update_data(city=text or None)
    await message.answer(
        "📝 Расскажи о себе (или пропусти):",
        reply_markup=skip_kb(),
    )
    await state.set_state(RegStates.bio)


@router.callback_query(RegStates.city, F.data == "skip_step")
async def skip_city(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(city=None)
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "📝 Расскажи о себе (или пропусти):",
            reply_markup=skip_kb(),
        )
    await state.set_state(RegStates.bio)


# ---------------------------------------------------------------------------
# bio
# ---------------------------------------------------------------------------

@router.message(RegStates.bio)
async def reg_bio(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    await state.update_data(bio=text[:500] if text else None)
    await message.answer("🔍 Кого ищешь?", reply_markup=preferred_gender_kb())
    await state.set_state(RegStates.pref_gender)


@router.callback_query(RegStates.bio, F.data == "skip_step")
async def skip_bio(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(bio=None)
    await callback.answer()
    if callback.message:
        await callback.message.answer("🔍 Кого ищешь?", reply_markup=preferred_gender_kb())
    await state.set_state(RegStates.pref_gender)


# ---------------------------------------------------------------------------
# pref_gender (callback)
# ---------------------------------------------------------------------------

@router.callback_query(RegStates.pref_gender, F.data.startswith("pref_gender:"))
async def reg_pref_gender(callback: CallbackQuery, state: FSMContext) -> None:
    pref = (callback.data or "").split(":")[1]
    await state.update_data(pref_gender=pref)
    await callback.answer()
    if callback.message:
        await callback.message.answer("🔞 Минимальный возраст партнёра? (18–99)")
    await state.set_state(RegStates.pref_min_age)


# ---------------------------------------------------------------------------
# pref_min_age
# ---------------------------------------------------------------------------

@router.message(RegStates.pref_min_age)
async def reg_pref_min_age(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (18 <= int(text) <= 99):
        await message.answer("Введи число от 18 до 99:")
        return
    await state.update_data(pref_min_age=int(text))
    await message.answer("🔝 Максимальный возраст партнёра? (18–99)")
    await state.set_state(RegStates.pref_max_age)


# ---------------------------------------------------------------------------
# pref_max_age
# ---------------------------------------------------------------------------

@router.message(RegStates.pref_max_age)
async def reg_pref_max_age(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    min_age = data.get("pref_min_age", 18)
    if not text.isdigit() or not (int(text) >= min_age):
        await message.answer(f"Введи число ≥ {min_age}:")
        return
    await state.update_data(pref_max_age=int(text))
    await message.answer(
        "📷 Отправь фото для анкеты (или пропусти):",
        reply_markup=skip_kb(),
    )
    await state.set_state(RegStates.photo)


# ---------------------------------------------------------------------------
# photo
# ---------------------------------------------------------------------------

@router.message(RegStates.photo, F.photo)
async def reg_photo(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    photo = message.photo[-1]
    file_id = photo.file_id

    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await bot.download_file(tg_file.file_path or "", buf)  # type: ignore[arg-type]
    file_bytes = buf.getvalue()

    data = await state.get_data()
    data["photo_file_id"] = file_id
    data["photo_bytes"] = file_bytes
    await state.update_data(
        photo_file_id=file_id,
        photo_bytes=file_bytes,
    )
    await _finish_registration(message, state, session, bot)


@router.callback_query(RegStates.photo, F.data == "skip_step")
async def skip_photo(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    await callback.answer()
    await _finish_registration(callback.message, state, session, bot)


# ---------------------------------------------------------------------------
# Сохранение в БД
# ---------------------------------------------------------------------------

async def _finish_registration(
    message: Message | None,
    state: FSMContext,
    session: AsyncSession,
    bot: Bot,
) -> None:
    if message is None:
        return

    data = await state.get_data()
    tg_id = message.chat.id
    tg_username: str | None = data.get("tg_username")

    user = await session.scalar(select(User).where(User.telegram_id == tg_id))
    if user is None:
        user = User(telegram_id=tg_id, username=tg_username)
        session.add(user)
        await session.flush()
    elif user.username != tg_username:
        user.username = tg_username

    # Profile
    profile = await session.scalar(
        select(Profile).where(Profile.user_id == user.id)
    )
    if profile:
        profile.name = data["name"]
        profile.age = data["age"]
        profile.gender = data["gender"]
        profile.city = data.get("city")
        profile.bio = data.get("bio")
    else:
        profile = Profile(
            user_id=user.id,
            name=data["name"],
            age=data["age"],
            gender=data["gender"],
            city=data.get("city"),
            bio=data.get("bio"),
        )
        session.add(profile)

    # Preferences
    prefs = await session.scalar(
        select(Preferences).where(Preferences.user_id == user.id)
    )
    if prefs:
        prefs.preferred_gender = data.get("pref_gender", "any")
        prefs.min_age = data.get("pref_min_age", 18)
        prefs.max_age = data.get("pref_max_age", 99)
    else:
        prefs = Preferences(
            user_id=user.id,
            preferred_gender=data.get("pref_gender", "any"),
            min_age=data.get("pref_min_age", 18),
            max_age=data.get("pref_max_age", 99),
        )
        session.add(prefs)

    await session.flush()

    # Photo (если загружено)
    photo_bytes: bytes | None = data.get("photo_bytes")
    photo_file_id: str | None = data.get("photo_file_id")
    if photo_bytes and photo_file_id:
        try:
            minio_url = await storage.upload_photo(photo_bytes, user.id)
        except Exception:
            logger.warning("MinIO upload failed, using tg_file_id as fallback")
            minio_url = photo_file_id

        existing_photos = await session.scalars(
            select(Photo).where(Photo.user_id == user.id)
        )
        for p in existing_photos:
            p.is_main = False

        session.add(
            Photo(
                user_id=user.id,
                url=minio_url,
                tg_file_id=photo_file_id,
                is_main=True,
            )
        )
        await session.flush()

    # Первичный рейтинг
    await rating_module.recalculate_rating(user.id, session)

    await state.clear()
    await message.answer(
        "✅ Анкета создана! Добро пожаловать.",
        reply_markup=main_menu_kb(),
    )
