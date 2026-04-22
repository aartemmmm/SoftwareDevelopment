from __future__ import annotations

import uuid

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


# ---------------------------------------------------------------------------
# Callback factories
# ---------------------------------------------------------------------------

class FeedAction(CallbackData, prefix="feed"):
    action: str       # "like" | "skip"
    target_id: str    # str(uuid)


class EditField(CallbackData, prefix="edit"):
    field: str        # "name" | "age" | "gender" | "city" | "bio" | "prefs"


# ---------------------------------------------------------------------------
# Reply keyboards
# ---------------------------------------------------------------------------

def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="👀 Смотреть анкеты"),
                KeyboardButton(text="👤 Моя анкета"),
            ],
            [KeyboardButton(text="💬 Мои мэтчи")],
        ],
        resize_keyboard=True,
    )


# ---------------------------------------------------------------------------
# Inline keyboards
# ---------------------------------------------------------------------------

def gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Мужской", callback_data="gender:male"),
                InlineKeyboardButton(text="Женский", callback_data="gender:female"),
            ]
        ]
    )


def preferred_gender_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Парней", callback_data="pref_gender:male"),
                InlineKeyboardButton(text="Девушек", callback_data="pref_gender:female"),
            ]
        ]
    )


def skip_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="skip_step")]
        ]
    )


def feed_action_kb(target_user_id: uuid.UUID) -> InlineKeyboardMarkup:
    tid = str(target_user_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="❤️ Лайк",
                    callback_data=FeedAction(action="like", target_id=tid).pack(),
                ),
                InlineKeyboardButton(
                    text="👎 Пропустить",
                    callback_data=FeedAction(action="skip", target_id=tid).pack(),
                ),
            ]
        ]
    )


def edit_profile_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Изменить имя", callback_data=EditField(field="name").pack()
                ),
                InlineKeyboardButton(
                    text="🎂 Возраст", callback_data=EditField(field="age").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏙 Город", callback_data=EditField(field="city").pack()
                ),
                InlineKeyboardButton(
                    text="📝 О себе", callback_data=EditField(field="bio").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Предпочтения", callback_data=EditField(field="prefs").pack()
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📷 Добавить фото", callback_data=EditField(field="photo").pack()
                ),
            ],
        ]
    )
