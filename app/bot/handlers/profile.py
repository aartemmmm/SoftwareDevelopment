"""
Profile handler — просмотр и редактирование своей анкеты.
"""
from __future__ import annotations

import io
import logging

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, default_state
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import EditField, edit_profile_kb, preferred_gender_kb, skip_kb
from app.db.models import Photo, Preferences, Profile, User
from app.modules import rating as rating_module
from app.modules import storage

logger = logging.getLogger(__name__)
router = Router()


class EditStates(StatesGroup):
    name = State()
    age = State()
    city = State()
    bio = State()
    pref_min_age = State()
    pref_max_age = State()
    pref_gender = State()
    photo = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user(tg_id: int, session: AsyncSession) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == tg_id))


async def _format_profile(user: User, session: AsyncSession) -> str:
    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        return "Анкета не найдена."

    prefs = await session.scalar(
        select(Preferences).where(Preferences.user_id == user.id)
    )

    gender_label = "Мужской" if profile.gender == "male" else "Женский"
    pref_map = {"male": "Парни", "female": "Девушки", "any": "Все"}
    pref_label = pref_map.get(prefs.preferred_gender, "Все") if prefs else "Все"

    lines = [
        f"👤 *{profile.name}*, {profile.age} лет",
        f"⚧ Пол: {gender_label}",
    ]
    if profile.city:
        lines.append(f"🏙 Город: {profile.city}")
    if profile.bio:
        lines.append(f"📝 {profile.bio}")
    if prefs:
        lines.append(
            f"\n🔍 Ищу: {pref_label}, {prefs.min_age}–{prefs.max_age} лет"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Show profile
# ---------------------------------------------------------------------------

@router.message(StateFilter(default_state), F.text == "👤 Моя анкета")
async def show_my_profile(message: Message, session: AsyncSession) -> None:
    tg_id = message.from_user.id if message.from_user else None
    if not tg_id:
        return

    user = await _get_user(tg_id, session)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start")
        return

    text = await _format_profile(user, session)

    photo = await session.scalar(
        select(Photo).where(Photo.user_id == user.id, Photo.is_main == True)
    )

    if photo and photo.tg_file_id:
        await message.answer_photo(
            photo=photo.tg_file_id,
            caption=text,
            parse_mode="Markdown",
            reply_markup=edit_profile_kb(),
        )
    else:
        await message.answer(
            text,
            parse_mode="Markdown",
            reply_markup=edit_profile_kb(),
        )


# ---------------------------------------------------------------------------
# Edit field dispatch
# ---------------------------------------------------------------------------

@router.callback_query(EditField.filter())
async def dispatch_edit(
    callback: CallbackQuery, callback_data: EditField, state: FSMContext
) -> None:
    field = callback_data.field
    await callback.answer()

    prompts = {
        "name": ("Введи новое имя:", EditStates.name),
        "age": ("Введи новый возраст (18–99):", EditStates.age),
        "city": ("Введи новый город (или пропусти):", EditStates.city),
        "bio": ("Напиши о себе (или пропусти):", EditStates.bio),
        "prefs": ("Кого ищешь?", EditStates.pref_gender),
        "photo": ("Отправь новое фото:", EditStates.photo),
    }

    if field not in prompts:
        return

    text, next_state = prompts[field]
    reply_markup = None
    if field in ("city", "bio", "photo"):
        reply_markup = skip_kb()
    elif field == "prefs":
        reply_markup = preferred_gender_kb()

    if callback.message:
        await callback.message.answer(text, reply_markup=reply_markup)
    await state.set_state(next_state)


# ---------------------------------------------------------------------------
# Edit name
# ---------------------------------------------------------------------------

@router.message(EditStates.name)
async def edit_name(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text or len(text) > 100:
        await message.answer("Имя должно быть от 1 до 100 символов:")
        return

    user = await _get_user(message.from_user.id, session)
    if not user:
        await state.clear()
        return

    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile:
        profile.name = text
        await session.flush()
        await rating_module.recalculate_rating(user.id, session)

    await state.clear()
    await message.answer(f"✅ Имя обновлено: {text}")


# ---------------------------------------------------------------------------
# Edit age
# ---------------------------------------------------------------------------

@router.message(EditStates.age)
async def edit_age(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (18 <= int(text) <= 99):
        await message.answer("Введи корректный возраст (18–99):")
        return

    user = await _get_user(message.from_user.id, session)
    if not user:
        await state.clear()
        return

    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile:
        profile.age = int(text)
        await session.flush()

    await state.clear()
    await message.answer(f"✅ Возраст обновлён: {text}")


# ---------------------------------------------------------------------------
# Edit city
# ---------------------------------------------------------------------------

@router.message(EditStates.city)
async def edit_city(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    user = await _get_user(message.from_user.id, session)
    if not user:
        await state.clear()
        return

    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile:
        profile.city = text[:100] if text else None
        await session.flush()
        await rating_module.recalculate_rating(user.id, session)

    await state.clear()
    await message.answer("✅ Город обновлён.")


@router.callback_query(EditStates.city, F.data == "skip_step")
async def skip_edit_city(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Изменение отменено.")


# ---------------------------------------------------------------------------
# Edit bio
# ---------------------------------------------------------------------------

@router.message(EditStates.bio)
async def edit_bio(message: Message, state: FSMContext, session: AsyncSession) -> None:
    text = (message.text or "").strip()
    user = await _get_user(message.from_user.id, session)
    if not user:
        await state.clear()
        return

    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile:
        profile.bio = text[:500] if text else None
        await session.flush()
        await rating_module.recalculate_rating(user.id, session)

    await state.clear()
    await message.answer("✅ Описание обновлено.")


@router.callback_query(EditStates.bio, F.data == "skip_step")
async def skip_edit_bio(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Изменение отменено.")


# ---------------------------------------------------------------------------
# Edit preferences: gender → min_age → max_age
# ---------------------------------------------------------------------------

@router.callback_query(EditStates.pref_gender, F.data.startswith("pref_gender:"))
async def edit_pref_gender(
    callback: CallbackQuery, state: FSMContext
) -> None:
    pref = (callback.data or "").split(":")[1]
    await state.update_data(pref_gender=pref)
    await callback.answer()
    if callback.message:
        await callback.message.answer("🔞 Минимальный возраст партнёра? (18–99)")
    await state.set_state(EditStates.pref_min_age)


@router.message(EditStates.pref_min_age)
async def edit_pref_min(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text.isdigit() or not (18 <= int(text) <= 99):
        await message.answer("Введи число от 18 до 99:")
        return
    await state.update_data(pref_min_age=int(text))
    await message.answer("🔝 Максимальный возраст партнёра? (18–99)")
    await state.set_state(EditStates.pref_max_age)


@router.message(EditStates.pref_max_age)
async def edit_pref_max(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    text = (message.text or "").strip()
    data = await state.get_data()
    min_age = data.get("pref_min_age", 18)
    if not text.isdigit() or int(text) < min_age:
        await message.answer(f"Введи число ≥ {min_age}:")
        return

    user = await _get_user(message.from_user.id, session)
    if not user:
        await state.clear()
        return

    prefs = await session.scalar(
        select(Preferences).where(Preferences.user_id == user.id)
    )
    if prefs:
        prefs.preferred_gender = data.get("pref_gender", "any")
        prefs.min_age = min_age
        prefs.max_age = int(text)
        await session.flush()
    else:
        session.add(
            Preferences(
                user_id=user.id,
                preferred_gender=data.get("pref_gender", "any"),
                min_age=min_age,
                max_age=int(text),
            )
        )
        await session.flush()

    await state.clear()
    await message.answer("✅ Предпочтения обновлены.")


# ---------------------------------------------------------------------------
# Edit photo
# ---------------------------------------------------------------------------

@router.message(EditStates.photo, F.photo)
async def edit_photo(
    message: Message, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    photo = message.photo[-1]
    file_id = photo.file_id

    tg_file = await bot.get_file(file_id)
    buf = io.BytesIO()
    await bot.download_file(tg_file.file_path or "", buf)  # type: ignore[arg-type]

    user = await _get_user(message.from_user.id, session)
    if not user:
        await state.clear()
        return

    try:
        minio_url = await storage.upload_photo(buf.getvalue(), user.id)
    except Exception:
        logger.warning("MinIO upload failed, fallback to tg_file_id")
        minio_url = file_id

    existing = await session.scalars(select(Photo).where(Photo.user_id == user.id))
    for p in existing:
        p.is_main = False

    session.add(
        Photo(
            user_id=user.id,
            url=minio_url,
            tg_file_id=file_id,
            is_main=True,
        )
    )
    await session.flush()
    await rating_module.recalculate_rating(user.id, session)

    await state.clear()
    await message.answer("✅ Фото обновлено.")


@router.callback_query(EditStates.photo, F.data == "skip_step")
async def skip_edit_photo(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer("Изменение отменено.")
