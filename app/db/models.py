from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), index=True
    )

    __table_args__ = (Index("ix_users_telegram_id", "telegram_id"),)

    profile: Mapped[Profile | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    photos: Mapped[list[Photo]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    preferences: Mapped[Preferences | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    rating: Mapped[Rating | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    sent_interactions: Mapped[list[Interaction]] = relationship(
        foreign_keys="Interaction.from_user_id",
        back_populates="from_user",
        cascade="all, delete-orphan",
    )
    received_interactions: Mapped[list[Interaction]] = relationship(
        foreign_keys="Interaction.to_user_id",
        back_populates="to_user",
        cascade="all, delete-orphan",
    )
    events: Mapped[list[UserEvent]] = relationship(
        foreign_keys="UserEvent.user_id",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class Profile(Base):
    __tablename__ = "profiles"

    __table_args__ = (
        Index("ix_profiles_gender", "gender"),
        Index("ix_profiles_age", "age"),
        Index("ix_profiles_gender_age", "gender", "age"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    interests: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship(back_populates="profile")


class Photo(Base):
    __tablename__ = "photos"

    __table_args__ = (
        Index("ix_photos_user_id_is_main", "user_id", "is_main"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    tg_file_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_main: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped[User] = relationship(back_populates="photos")


class Preferences(Base):
    __tablename__ = "preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    preferred_gender: Mapped[str] = mapped_column(
        String(10), nullable=False, default="any"
    )
    min_age: Mapped[int] = mapped_column(Integer, default=18)
    max_age: Mapped[int] = mapped_column(Integer, default=99)

    user: Mapped[User] = relationship(back_populates="preferences")


class Interaction(Base):
    __tablename__ = "interactions"

    __table_args__ = (
        Index("ix_interactions_from_user_id", "from_user_id"),
        Index("ix_interactions_to_user_id", "to_user_id"),
        Index("ix_interactions_created_at", "created_at"),
        Index("ix_interactions_from_to_action", "from_user_id", "to_user_id", "action"),
        Index("ix_interactions_to_action", "to_user_id", "action"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    from_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    to_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    from_user: Mapped[User] = relationship(
        foreign_keys=[from_user_id], back_populates="sent_interactions"
    )
    to_user: Mapped[User] = relationship(
        foreign_keys=[to_user_id], back_populates="received_interactions"
    )


class Match(Base):
    __tablename__ = "matches"

    __table_args__ = (
        Index("ix_matches_user1_id", "user1_id"),
        Index("ix_matches_user2_id", "user2_id"),
        Index("ix_matches_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user1_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    user2_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    chat_messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="match", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    """In-match messages (stored in DB; UI delivers via Telegram links)."""

    __tablename__ = "chat_messages"

    __table_args__ = (
        Index("ix_chat_messages_match_id", "match_id"),
        Index("ix_chat_messages_sender_id", "sender_id"),
        Index("ix_chat_messages_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    match: Mapped[Match] = relationship(back_populates="chat_messages")


class Rating(Base):
    """
    User rating table.

    level1_score — profile completeness score (static quality)
    level2_score — behavioral score (likes received, match rate)
    final_score  — weighted combination; used for feed ordering
    """

    __tablename__ = "ratings"

    __table_args__ = (
        Index("ix_ratings_final_score", "final_score"),
        Index("ix_ratings_updated_at", "updated_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    level1_score: Mapped[float] = mapped_column(Float, default=0.0)
    level2_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship(back_populates="rating")


class UserEvent(Base):
    """
    Analytics event log.

    Records all domain events (like, skip, match, message) for analytics,
    conversion tracking and activity reports.
    Consumers: Celery workers via RabbitMQ.
    """

    __tablename__ = "user_events"

    __table_args__ = (
        Index("ix_user_events_user_id", "user_id"),
        Index("ix_user_events_event_type", "event_type"),
        Index("ix_user_events_created_at", "created_at"),
        Index("ix_user_events_type_date", "event_type", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    target_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped[User] = relationship(
        foreign_keys=[user_id], back_populates="events"
    )
