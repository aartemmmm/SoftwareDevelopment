"""
Storage Module — загрузка фотографий в MinIO (S3-совместимое хранилище).
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from minio import Minio
from minio.error import S3Error

load_dotenv(Path(__file__).parent.parent.parent / ".env", override=True)

logger = logging.getLogger(__name__)

_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
_BUCKET = os.environ.get("MINIO_BUCKET", "photos")
_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"


def _get_client() -> Minio:
    return Minio(
        endpoint=_ENDPOINT,
        access_key=_ACCESS_KEY,
        secret_key=_SECRET_KEY,
        secure=_SECURE,
    )


def _ensure_bucket(client: Minio) -> None:
    if not client.bucket_exists(_BUCKET):
        client.make_bucket(_BUCKET)
        logger.info("MinIO bucket '%s' created", _BUCKET)


def _upload_sync(file_bytes: bytes, user_id: uuid.UUID) -> str:
    client = _get_client()
    _ensure_bucket(client)
    object_name = f"users/{user_id}/{uuid.uuid4()}.jpg"
    client.put_object(
        _BUCKET,
        object_name,
        io.BytesIO(file_bytes),
        length=len(file_bytes),
        content_type="image/jpeg",
    )
    protocol = "https" if _SECURE else "http"
    url = f"{protocol}://{_ENDPOINT}/{_BUCKET}/{object_name}"
    logger.info("Photo uploaded to MinIO: %s", url)
    return url


async def upload_photo(file_bytes: bytes, user_id: uuid.UUID) -> str:
    """Загрузить фото в MinIO и вернуть URL объекта."""
    return await asyncio.to_thread(_upload_sync, file_bytes, user_id)


def _presign_sync(object_name: str) -> str:
    from datetime import timedelta
    client = _get_client()
    return client.presigned_get_object(_BUCKET, object_name, expires=timedelta(hours=1))


async def presign_url(object_name: str) -> str:
    """Получить presigned URL для доступа к объекту."""
    return await asyncio.to_thread(_presign_sync, object_name)
