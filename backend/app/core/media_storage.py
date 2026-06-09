"""Durable media storage for uploaded images (staff photos, avatars, room photos).

The container filesystem on hosts like Render is *ephemeral* — anything written
to local disk is wiped on every deploy/restart. To keep uploads, we store them in
Supabase Storage (object storage) when it is configured, and fall back to the
local media directory for local development / docker where Supabase is not set up.

A stored image is referenced by the URL this module returns:
  * Supabase:  https://<project>.supabase.co/storage/v1/object/public/<bucket>/<path>
  * Local:     /assets/media/<path>   (served by the StaticFiles mount in main.py)

The frontend uses these URLs directly as image `src`, so both forms work as-is.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Local fallback root — mirrors the historical layout under the served /assets path.
FRONTEND_MEDIA_DIR = Path(__file__).resolve().parents[1] / "frontend" / "media"

_LOCAL_URL_PREFIX = "/assets/media/"
_SUPABASE_PUBLIC_MARKER = "/storage/v1/object/public/"


def supabase_storage_enabled() -> bool:
    """True when uploads should go to Supabase Storage (durable) rather than disk."""
    return bool(
        settings.SUPABASE_URL
        and settings.SUPABASE_SERVICE_KEY
        and settings.SUPABASE_STORAGE_BUCKET
    )


def store_media(
    file_bytes: bytes,
    *,
    folder: str,
    extension: str = "jpg",
    content_type: str = "image/jpeg",
) -> str:
    """Persist an image and return the URL to reference it by.

    `folder` is the logical subfolder ("staff", "avatars", "rooms"). Uploads to
    Supabase when configured; otherwise writes to the local media directory.
    """
    object_path = f"{folder}/{uuid4().hex}.{extension}"
    if supabase_storage_enabled():
        return _upload_to_supabase(object_path, file_bytes, content_type)
    return _save_to_local(object_path, file_bytes)


def delete_media(media_url: Optional[str]) -> None:
    """Best-effort deletion of a previously stored image (Supabase or local).

    Never raises: cleanup must not break the request that triggered it.
    """
    if not media_url:
        return
    try:
        if _SUPABASE_PUBLIC_MARKER in media_url:
            _delete_from_supabase(media_url)
        elif media_url.startswith(_LOCAL_URL_PREFIX):
            local_path = FRONTEND_MEDIA_DIR / media_url[len(_LOCAL_URL_PREFIX):]
            if local_path.exists():
                local_path.unlink()
    except Exception:  # noqa: BLE001 - cleanup is strictly best-effort
        logger.warning("Failed to delete media %s", media_url, exc_info=True)


# ── Supabase Storage (REST) ────────────────────────────────────────────────


def _supabase_object_url(object_path: str) -> str:
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.SUPABASE_STORAGE_BUCKET
    return f"{base}/storage/v1/object/{bucket}/{object_path}"


def _upload_to_supabase(object_path: str, file_bytes: bytes, content_type: str) -> str:
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.SUPABASE_STORAGE_BUCKET
    resp = httpx.post(
        _supabase_object_url(object_path),
        content=file_bytes,
        headers={
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Content-Type": content_type,
            "x-upsert": "true",
            "cache-control": "max-age=3600",
        },
        timeout=settings.SUPABASE_TIMEOUT_SECONDS,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"Supabase Storage upload failed ({resp.status_code}): {resp.text[:300]}"
        )
    return f"{base}/storage/v1/object/public/{bucket}/{object_path}"


def _delete_from_supabase(media_url: str) -> None:
    base = settings.SUPABASE_URL.rstrip("/")
    # Public URL: <base>/storage/v1/object/public/<bucket>/<path>
    _, _, bucket_and_path = media_url.partition(_SUPABASE_PUBLIC_MARKER)
    if not bucket_and_path:
        return
    bucket, _, object_path = bucket_and_path.partition("/")
    if not object_path:
        return
    resp = httpx.request(
        "DELETE",
        f"{base}/storage/v1/object/{bucket}/{object_path}",
        headers={
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_KEY,
        },
        timeout=settings.SUPABASE_TIMEOUT_SECONDS,
    )
    if resp.status_code >= 400 and resp.status_code != 404:
        logger.warning(
            "Supabase Storage delete failed (%s): %s", resp.status_code, resp.text[:300]
        )


# ── Local disk fallback (dev / docker) ─────────────────────────────────────


def _save_to_local(object_path: str, file_bytes: bytes) -> str:
    dest = FRONTEND_MEDIA_DIR / object_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(file_bytes)
    return f"{_LOCAL_URL_PREFIX}{object_path}"
