"""
Feed handler — browse profiles, like / skip, match notifications.

Event flow (every like / skip):
  handler
    ├── matching.record_interaction()          DB write (interaction + maybe match)
    ├── event_bus.publish_like/skip/match()   → RabbitMQ 'dating_events' exchange
    │       └── analytics consumer reads it   (real-time counters, hourly patterns)
    ├── events.publish_like/skip/match()      → Celery via RabbitMQ
    │       └── worker: rating recalc + DB event log
    └── events.publish_warm_cache()            prefetch next batch for this user
"""
from __future__ import annotations

import logging
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import FeedAction, feed_action_kb, main_menu_kb
from app.db.models import Match, Photo, Profile, Rating, User
from app.modules import event_bus
from app.modules import events as event_celery
from app.modules import matching as matching_module
from app.modules.metrics import increment_event, mark_user_active, record_hourly_activity
from app.services.notifications import NotificationService

logger = logging.getLogger(__name__)
router = Router()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_user_by_tg(tg_id: int, session: AsyncSession) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == tg_id))


async def _build_profile_card(
    target_user_id: uuid.UUID, session: AsyncSession
) -> tuple[str, str | None]:
    """Return (card_text, tg_file_id | None)."""
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
    if profile.interests:
        lines.append(f"🎯 {profile.interests}")
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
            photo=tg_file_id, caption=text, parse_mode="Markdown", reply_markup=kb
        )
    else:
        await message.answer(text, parse_mode="Markdown", reply_markup=kb)


# ── Browse ────────────────────────────────────────────────────────────────────

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

    await mark_user_active(user.id, redis)

    next_id = await matching_module.get_next_profile_id(user.id, session, redis)
    if not next_id:
        await message.answer(
            "😔 Анкеты закончились. Попробуй позже!", reply_markup=main_menu_kb()
        )
        return

    await _show_profile(message, next_id, session)


# ── Like / Skip ───────────────────────────────────────────────────────────────

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

    action    = callback_data.action
    target_id = uuid.UUID(callback_data.target_id)

    match = await matching_module.record_interaction(user.id, target_id, action, session)

    # ── Resolve parties for notifications ────────────────────────────────────
    target_user    = await session.scalar(select(User).where(User.id == target_id))
    target_profile = await session.scalar(select(Profile).where(Profile.user_id == target_id))
    my_profile     = await session.scalar(select(Profile).where(Profile.user_id == user.id))

    notifier = NotificationService(bot)

    # ── Notifications via dedicated service ──────────────────────────────────
    if action == "like" and target_user and target_profile and my_profile:
        if match:
            await notifier.notify_match(
                actor=user,
                actor_profile=my_profile,
                partner=target_user,
                partner_profile=target_profile,
            )
        else:
            await notifier.notify_like(
                liker=user,
                liker_profile=my_profile,
                liked_user=target_user,
                session=session,
            )

    await callback.answer("❤️ Лайк!" if action == "like" else "👎 Пропуск")

    # ── Publish to RabbitMQ event bus (analytics consumer) ───────────────────
    if action == "like":
        await event_bus.publish_like(user.id, target_id)
        if match:
            await event_bus.publish_match(user.id, target_id)
    else:
        await event_bus.publish_skip(user.id, target_id)

    # ── Publish Celery tasks (rating recalc, cache warm, DB logging) ─────────
    if action == "like":
        event_celery.publish_like_event(user.id, target_id)
        if match:
            event_celery.publish_match_event(user.id, target_id)
    else:
        event_celery.publish_skip_event(user.id, target_id)

    event_celery.publish_warm_cache(user.id)

    # ── Update real-time Redis metrics ────────────────────────────────────────
    await increment_event(action, redis)
    await record_hourly_activity(action, redis)
    await mark_user_active(user.id, redis)

    # ── Show next profile ─────────────────────────────────────────────────────
    next_id = await matching_module.get_next_profile_id(user.id, session, redis)
    if not next_id:
        await callback.message.answer(
            "😔 Анкеты закончились. Попробуй позже!", reply_markup=main_menu_kb()
        )
        return

    await _show_profile(callback.message, next_id, session)


# ── My matches ────────────────────────────────────────────────────────────────

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
    for i, m in enumerate(matches, 1):
        partner_id = m.user2_id if m.user1_id == user.id else m.user1_id
        partner_profile = await session.scalar(
            select(Profile).where(Profile.user_id == partner_id)
        )
        partner_user = await session.scalar(select(User).where(User.id == partner_id))
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
