"""
Standalone RabbitMQ analytics consumer.

Subscribes to the 'dating_events' topic exchange as an independent service.
Processes all domain events: like, skip, match, message.

Responsibilities:
  - Increment Redis real-time counters (likes/skips/matches today)
  - Record hourly activity patterns
  - Persist UserEvent rows to DB for historical analytics
  - Completely separate from Celery — demonstrates true event-driven pattern

Run:
    python -m app.services.event_consumer

Docker service: see docker-compose.yml 'event-consumer'
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as __main__
_ROOT = Path(__file__).parent.parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=True)

import aio_pika
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_EXCHANGE   = "dating_events"
_QUEUE_NAME = "analytics"


def _broker_url() -> str:
    u    = os.environ.get("RABBITMQ_USER",     "guest")
    p    = os.environ.get("RABBITMQ_PASSWORD", "guest")
    h    = os.environ.get("RABBITMQ_HOST",     "localhost")
    port = os.environ.get("RABBITMQ_PORT",     "5672")
    return f"amqp://{u}:{p}@{h}:{port}/"


async def _handle_event(event_type: str, payload: dict, redis: Redis) -> None:
    """Route an incoming event to the appropriate analytics handler."""
    from app.modules.metrics import increment_event, record_hourly_activity, record_event_sync

    await increment_event(event_type, redis)
    await record_hourly_activity(event_type, redis)

    from_id = payload.get("from_user_id") or payload.get("user1_id") or payload.get("sender_id")
    to_id   = payload.get("to_user_id")   or payload.get("user2_id")

    if from_id:
        record_event_sync(event_type, from_id, to_id)

    logger.info(
        "[consumer] event=%s from=%s to=%s",
        event_type, from_id, to_id,
    )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logger.info("[consumer] Starting event consumer…")

    redis = Redis.from_url(
        os.environ.get("REDIS_URL", "redis://localhost:6379"),
        decode_responses=True,
    )

    connection = await aio_pika.connect_robust(_broker_url(), heartbeat=60)
    channel    = await connection.channel()
    await channel.set_qos(prefetch_count=20)

    exchange = await channel.declare_exchange(
        _EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True
    )
    queue = await channel.declare_queue(_QUEUE_NAME, durable=True)
    await queue.bind(exchange, routing_key="event.*")

    logger.info("[consumer] Bound to exchange '%s' queue '%s'", _EXCHANGE, _QUEUE_NAME)

    async def on_message(message: aio_pika.IncomingMessage) -> None:
        async with message.process(requeue_on_timeout=True):
            try:
                data       = json.loads(message.body)
                event_type = data.pop("event_type", "unknown")
                await _handle_event(event_type, data, redis)
            except Exception:
                logger.exception("[consumer] Failed to process message")

    await queue.consume(on_message)
    logger.info("[consumer] Listening… Press Ctrl+C to stop.")
    try:
        await asyncio.Future()
    finally:
        await redis.aclose()
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
