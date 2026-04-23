from __future__ import annotations

import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import FeedAction, feed_action_kb, main_menu_kb
from app.db.models import Match, Photo, Preferences, Profile, Rating, User
from app.modules import matching as matching_module

logger = logging.getLogger(__name__)
router = Router()

async def _get_user_by_tg(tg_id: int, session: AsyncSession) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == tg_id))


async def _build_profile_card(
    target_user_id: uuid.UUID, session: AsyncSession
) -> tuple[str, str | None]:
    """
    Возвращает (текст_карточки, tg_file_id | None).
    """
    profile = await session.scalar(
        select(Profile).where(Profile.user_id == target_user_id)
    )
    if not profile:
        return ("Анкета недоступна", None)

    rating = await session.scalar(
        select(Rating).where(Rating.user_id == target_user_id)
    )
    photo = await session.scalar(
        select(Photo).where(
            Photo.user_id == target_user_id, Photo.is_main == True
        )
    )

    gender_label = "Парень" if profile.gender == "male" else "Девушка"
    lines = [f"*{profile.name}*, {profile.age} — {gender_label}"]
    if profile.city:
        lines.append(f"🏙 {profile.city}")
    if profile.bio:
        lines.append(f"📝 {profile.bio}")
    if rating:
        lines.append(f"\n⭐ Рейтинг: {rating.final_score:.1f}")

    return "\n".join(lines), (photo.tg_file_id if photo else None)


async def _show_profile(
    message: Message,
    target_user_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    text, tg_file_id = await _build_profile_card(target_user_id, session)
    kb = feed_action_kb(target_user_id)

    if tg_file_id:
        await message.answer_photo(
            photo=tg_file_id,
            caption=text,
            parse_mode="Markdown",
            reply_markup=kb,
        )
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)



@router.message(StateFilter(default_state), F.text == "👀 Смотреть анкеты")
async def cmd_browse(
    message: Message, session: AsyncSession, redis: Redis
) -> None:
    tg_id = message.from_user.id if message.from_user else None
    if not tg_id:
        return

    user = await _get_user_by_tg(tg_id, session)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start")
        return

    profile = await session.scalar(select(Profile).where(Profile.user_id == user.id))
    if not profile:
        await message.answer("Сначала заполни анкету через /start")
        return

    next_id = await matching_module.get_next_profile_id(user.id, session, redis)
    if not next_id:
        await message.answer(
            "😔 Анкеты закончились. Попробуй позже!",
            reply_markup=main_menu_kb(),
        )
        return

    await _show_profile(message, next_id, session)


@router.callback_query(FeedAction.filter())
async def handle_feed_action(
    callback: CallbackQuery,
    callback_data: FeedAction,
    session: AsyncSession,
    redis: Redis,
    bot: Bot,
) -> None:
    tg_id = callback.from_user.id if callback.from_user else None
    if not tg_id or not callback.message:
        await callback.answer()
        return

    user = await _get_user_by_tg(tg_id, session)
    if not user:
        await callback.answer("Сначала зарегистрируйся.", show_alert=True)
        return

    action = callback_data.action
    target_id = uuid.UUID(callback_data.target_id)

    match = await matching_module.record_interaction(user.id, target_id, action, session)

    target_user = await session.scalar(select(User).where(User.id == target_id))
    target_profile = await session.scalar(
        select(Profile).where(Profile.user_id == target_id)
    )
    my_profile = await session.scalar(
        select(Profile).where(Profile.user_id == user.id)
    )
    my_name = my_profile.name if my_profile else "Кто-то"
    their_name = target_profile.name if target_profile else "Кто-то"

    if action == "like":
        def _link(name: str, username: str | None, tg_id_val: int) -> str:
            if username:
                return f"[@{username}](https://t.me/{username})"
            return f"[{name}](tg://user?id={tg_id_val})"

        if match:
            their_link = _link(their_name, target_user.username if target_user else None,
                               target_user.telegram_id if target_user else 0)
            my_link = _link(my_name, user.username, tg_id)

            await callback.message.answer(
                f"🎉 Мэтч! *{their_name}* тоже лайкнул(а) тебя!\n"
                f"Написать: {their_link}",
                parse_mode="Markdown",
            )
            if target_user:
                try:
                    await bot.send_message(
                        chat_id=target_user.telegram_id,
                        text=f"🎉 Мэтч! *{my_name}* лайкнул(а) тебя!\n"
                             f"Написать: {my_link}",
                        parse_mode="Markdown",
                    )
                except Exception:
                    logger.warning(
                        "Could not send match notification to user %s",
                        target_user.telegram_id,
                    )
        else:
            if target_user:
                try:
                    card_text, card_photo = await _build_profile_card(user.id, session)
                    notify_text = f"💝 *{my_name}* лайкнул(а) тебя!\n\n{card_text}"
                    notify_kb = feed_action_kb(user.id)   # кнопки с ID лайкнувшего

                    if card_photo:
                        await bot.send_photo(
                            chat_id=target_user.telegram_id,
                            photo=card_photo,
                            caption=notify_text,
                            parse_mode="Markdown",
                            reply_markup=notify_kb,
                        )
                    else:
                        await bot.send_message(
                            chat_id=target_user.telegram_id,
                            text=notify_text,
                            parse_mode="Markdown",
                            reply_markup=notify_kb,
                        )
                except Exception:
                    logger.warning(
                        "Could not send like notification to user %s",
                        target_user.telegram_id,
                    )

    await callback.answer("❤️ Лайк!" if action == "like" else "👎 Пропуск")

    if action == "like":
        try:
            from tasks import recalculate_user_rating
            recalculate_user_rating.delay(str(target_id))
        except Exception:
            logger.debug("Celery not available, skipping async rating update")

    next_id = await matching_module.get_next_profile_id(user.id, session, redis)
    if not next_id:
        await callback.message.answer(
            "😔 Анкеты закончились. Попробуй позже!",
            reply_markup=main_menu_kb(),
        )
        return

    await _show_profile(callback.message, next_id, session)


@router.message(StateFilter(default_state), F.text == "💬 Мои мэтчи")
async def show_matches(message: Message, session: AsyncSession) -> None:
    tg_id = message.from_user.id if message.from_user else None
    if not tg_id:
        return

    user = await _get_user_by_tg(tg_id, session)
    if not user:
        await message.answer("Сначала зарегистрируйся через /start")
        return

    matches = list(
        await session.scalars(
            select(Match).where(
                or_(Match.user1_id == user.id, Match.user2_id == user.id)
            )
        )
    )

    if not matches:
        await message.answer("У тебя пока нет мэтчей. Лайкай анкеты! 😊")
        return

    lines = ["💬 *Твои мэтчи:*\n"]
    for i, match in enumerate(matches, 1):
        partner_id = match.user2_id if match.user1_id == user.id else match.user1_id
        partner_profile = await session.scalar(
            select(Profile).where(Profile.user_id == partner_id)
        )
        partner_user = await session.scalar(
            select(User).where(User.id == partner_id)
        )
        if not partner_profile or not partner_user:
            continue

        if partner_user.username:
            contact = f"[@{partner_user.username}](https://t.me/{partner_user.username})"
        else:
            contact = f"[Написать](tg://user?id={partner_user.telegram_id})"

        lines.append(
            f"{i}. *{partner_profile.name}*, {partner_profile.age} лет — {contact}"
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")
