"""
Async event bus — direct AMQP publisher via aio-pika.

Architecture:
                    ┌─── Celery worker  (heavy: rating recalc, cache warm)
  bot handler ──► RabbitMQ exchange
  (publish_*)       └─── analytics consumer (real-time metrics, UserEvent log)

Exchange: 'dating_events'  (topic, durable)
Routing keys:
  event.like    — user liked another user
  event.skip    — user skipped another user
  event.match   — mutual like, match created
  event.message — message sent inside a match

This module is called from async bot handlers (aiogram).
For Celery-based background processing see app/modules/events.py.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)

_EXCHANGE = "dating_events"


def _broker_url() -> str:
    u = os.environ.get("RABBITMQ_USER", "guest")
    p = os.environ.get("RABBITMQ_PASSWORD", "guest")
    h = os.environ.get("RABBITMQ_HOST", "localhost")
    port = os.environ.get("RABBITMQ_PORT", "5672")
    return f"amqp://{u}:{p}@{h}:{port}/"


async def publish_event(event_type: str, payload: dict[str, Any]) -> None:
    """
    Publish a domain event to the 'dating_events' topic exchange.
    Non-blocking: connection is opened per-call with a short timeout.
    Failures are swallowed — analytics delivery is best-effort.
    """
    try:
        import aio_pika

        connection = await aio_pika.connect_robust(_broker_url(), timeout=3)
        async with connection:
            channel  = await connection.channel()
            exchange = await channel.declare_exchange(
                _EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
            )
            body = json.dumps({"event_type": event_type, **payload}).encode()
            msg  = aio_pika.Message(
                body=body,
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            )
            await exchange.publish(msg, routing_key=f"event.{event_type}")
            logger.debug("[event_bus] Published event.%s", event_type)

    except ImportError:
        logger.debug("[event_bus] aio-pika not installed, skipping direct publish")
    except Exception as exc:
        logger.warning("[event_bus] Publish failed event=%s: %s", event_type, exc)


async def publish_like(from_user_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
    await publish_event("like", {
        "from_user_id": str(from_user_id),
        "to_user_id":   str(to_user_id),
    })


async def publish_skip(from_user_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
    await publish_event("skip", {
        "from_user_id": str(from_user_id),
        "to_user_id":   str(to_user_id),
    })


async def publish_match(user1_id: uuid.UUID, user2_id: uuid.UUID) -> None:
    await publish_event("match", {
        "user1_id": str(user1_id),
        "user2_id": str(user2_id),
    })


async def publish_message(sender_id: uuid.UUID, match_id: uuid.UUID) -> None:
    await publish_event("message", {
        "sender_id": str(sender_id),
        "match_id":  str(match_id),
    })
