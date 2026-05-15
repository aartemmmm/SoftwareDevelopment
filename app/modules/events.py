"""
Event publishing module.

Architecture:
    bot handler ──► events.publish_*() ──► Celery task ──► RabbitMQ queue
                                                            └──► worker consumes
                                                                 ├── updates rating
                                                                 ├── records analytics
                                                                 └── warms cache

All publish functions are fire-and-forget:
  - if Celery / RabbitMQ is unavailable, a WARNING is logged and execution continues
  - no exceptions are propagated to the bot handler
"""
from __future__ import annotations

import logging
import uuid

logger = logging.getLogger(__name__)


def _publish(task_name: str, *args: str) -> bool:
    """Send a Celery task to RabbitMQ with graceful degradation."""
    try:
        import importlib
        tasks = importlib.import_module("tasks")
        task = getattr(tasks, task_name)
        task.delay(*args)
        logger.debug("Event → MQ  task=%s args=%s", task_name, args)
        return True
    except Exception as exc:
        logger.warning("MQ publish failed task=%s: %s", task_name, exc)
        return False


# ── Domain event publishers ───────────────────────────────────────────────────

def publish_like_event(from_user_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
    """
    like_event: bot → MQ → worker
    Worker: records analytics + triggers rating recalculation for recipient.
    """
    _publish("process_like_event", str(from_user_id), str(to_user_id))


def publish_skip_event(from_user_id: uuid.UUID, to_user_id: uuid.UUID) -> None:
    """
    skip_event: bot → MQ → worker
    Worker: records analytics only (skip doesn't affect recipient rating).
    """
    _publish("process_skip_event", str(from_user_id), str(to_user_id))


def publish_match_event(user1_id: uuid.UUID, user2_id: uuid.UUID) -> None:
    """
    match_event: bot → MQ → worker
    Worker: records analytics + recalculates rating for both users.
    """
    _publish("process_match_event", str(user1_id), str(user2_id))


def publish_message_event(sender_id: uuid.UUID, match_id: uuid.UUID) -> None:
    """
    message_event: bot → MQ → worker
    Worker: records messaging analytics.
    """
    _publish("process_message_event", str(sender_id), str(match_id))


def publish_warm_cache(user_id: uuid.UUID) -> None:
    """
    Proactively warm feed cache for a user in the background.
    Called after each interaction so the next batch is ready instantly.
    """
    _publish("warm_user_feed_cache", str(user_id))
