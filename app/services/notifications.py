"""
Notification service — centralised delivery of all in-app Telegram notifications.

Decouples notification logic from bot handlers (feed.py).
Each method is responsible for exactly one notification type and handles
all Telegram API errors gracefully.

Usage:
    from app.services.notifications import NotificationService

    svc = NotificationService(bot)
    await svc.notify_like(liker, liked_user, my_profile, their_profile)
    await svc.notify_match(user1, user2, profile1, profile2)
"""
from __future__ import annotations

import logging
import uuid

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Photo, Profile, User

logger = logging.getLogger(__name__)


def _tg_link(name: str, username: str | None, tg_id: int) -> str:
    if username:
        return f"[@{username}](https://t.me/{username})"
    return f"[{name}](tg://user?id={tg_id})"


async def _get_main_photo(user_id: uuid.UUID, session: AsyncSession) -> str | None:
    photo = await session.scalar(
        select(Photo).where(Photo.user_id == user_id, Photo.is_main == True)
    )
    return photo.tg_file_id if photo else None


class NotificationService:
    """
    Centralised notification dispatcher.

    All methods return silently on delivery failure —
    notifications are best-effort and must never block the main flow.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def notify_like(
        self,
        liker: User,
        liker_profile: Profile,
        liked_user: User,
        session: AsyncSession,
    ) -> None:
        """
        Notify `liked_user` that `liker` liked their profile.
        Sends the liker's card with action buttons so the recipient
        can immediately like back (or skip).
        """
        from app.bot.keyboards import feed_action_kb

        try:
            rating_text = ""
            from app.db.models import Rating
            rating = await session.scalar(
                select(Rating).where(Rating.user_id == liker.id)
            )
            if rating:
                rating_text = f"\n⭐ Рейтинг: {rating.final_score:.1f}"

            gender_label = "Парень" if liker_profile.gender == "male" else "Девушка"
            lines = [
                f"💝 *{liker_profile.name}* лайкнул(а) тебя!",
                "",
                f"*{liker_profile.name}*, {liker_profile.age} — {gender_label}",
            ]
            if liker_profile.city:
                lines.append(f"🏙 {liker_profile.city}")
            if liker_profile.bio:
                lines.append(f"📝 {liker_profile.bio}")
            if liker_profile.interests:
                lines.append(f"🎯 {liker_profile.interests}")
            lines.append(rating_text)

            card_text = "\n".join(lines)
            photo_id  = await _get_main_photo(liker.id, session)
            kb        = feed_action_kb(liker.id)

            if photo_id:
                await self.bot.send_photo(
                    chat_id=liked_user.telegram_id,
                    photo=photo_id,
                    caption=card_text,
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            else:
                await self.bot.send_message(
                    chat_id=liked_user.telegram_id,
                    text=card_text,
                    parse_mode="Markdown",
                    reply_markup=kb,
                )
            logger.info("[notify] like sent → user %s", liked_user.telegram_id)

        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.warning("[notify] like blocked → user %s: %s", liked_user.telegram_id, exc)
        except Exception:
            logger.exception("[notify] like failed → user %s", liked_user.telegram_id)

    async def notify_match(
        self,
        actor: User,
        actor_profile: Profile,
        partner: User,
        partner_profile: Profile,
    ) -> None:
        """
        Send match congratulation to both parties with a contact link.
        """
        try:
            actor_link   = _tg_link(actor_profile.name,   actor.username,   actor.telegram_id)
            partner_link = _tg_link(partner_profile.name, partner.username, partner.telegram_id)

            await self.bot.send_message(
                chat_id=actor.telegram_id,
                text=(
                    f"🎉 Мэтч! *{partner_profile.name}* тоже лайкнул(а) тебя!\n"
                    f"Написать: {partner_link}"
                ),
                parse_mode="Markdown",
            )
            await self.bot.send_message(
                chat_id=partner.telegram_id,
                text=(
                    f"🎉 Мэтч! *{actor_profile.name}* лайкнул(а) тебя!\n"
                    f"Написать: {actor_link}"
                ),
                parse_mode="Markdown",
            )
            logger.info(
                "[notify] match sent: %s <-> %s",
                actor.telegram_id, partner.telegram_id,
            )

        except (TelegramForbiddenError, TelegramBadRequest) as exc:
            logger.warning("[notify] match blocked: %s", exc)
        except Exception:
            logger.exception("[notify] match failed")

    async def notify_system(self, user: User, text: str) -> None:
        """Generic system notification (e.g., account events, admin messages)."""
        try:
            await self.bot.send_message(chat_id=user.telegram_id, text=text)
        except Exception:
            logger.warning("[notify] system failed → user %s", user.telegram_id)
