from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock
from typing import Optional
from uuid import uuid4

from app.config import settings

try:
    import redis
except ImportError:  # pragma: no cover - optional local dependency
    redis = None


_memory_lock = Lock()
_memory_holds: dict[str, tuple[float, str]] = {}


@dataclass
class ReservationHold:
    token: str
    expires_at: int
    slot_keys: list[str]


def _redis_client():
    if redis is None:
        return None
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _cleanup_expired_memory_holds() -> None:
    now = time.time()
    expired_keys = [key for key, value in _memory_holds.items() if value[0] <= now]
    for key in expired_keys:
        _memory_holds.pop(key, None)


def create_hold(slot_keys: list[str], ttl_seconds: Optional[int] = None) -> ReservationHold:
    ttl_seconds = ttl_seconds or settings.RESERVATION_HOLD_MINUTES * 60
    expires_at = int(time.time()) + ttl_seconds
    token = f"hold_{uuid4().hex}"
    redis_client = _redis_client()

    if redis_client is not None:
        pipeline = redis_client.pipeline()
        for slot_key in slot_keys:
            pipeline.set(slot_key, token, nx=True, ex=ttl_seconds)
        results = pipeline.execute()
        if not all(results):
            release_hold(slot_keys, token)
            raise ValueError("One or more slots are already on hold")
        return ReservationHold(token=token, expires_at=expires_at, slot_keys=slot_keys)

    with _memory_lock:
        _cleanup_expired_memory_holds()
        for slot_key in slot_keys:
            if slot_key in _memory_holds:
                raise ValueError("One or more slots are already on hold")
        for slot_key in slot_keys:
            _memory_holds[slot_key] = (time.time() + ttl_seconds, token)

    return ReservationHold(token=token, expires_at=expires_at, slot_keys=slot_keys)


def active_held_slot_keys(slot_keys: list[str], *, ignore_token: Optional[str] = None) -> set[str]:
    """Of the given slot keys, return those currently held — optionally ignoring
    holds owned by `ignore_token` (so a caller's own hold doesn't hide the slot
    from their own availability view)."""
    if not slot_keys:
        return set()
    keys = list(slot_keys)
    held: set[str] = set()
    redis_client = _redis_client()
    if redis_client is not None:
        for key, value in zip(keys, redis_client.mget(keys)):
            if value is not None and value != ignore_token:
                held.add(key)
        return held

    with _memory_lock:
        _cleanup_expired_memory_holds()
        for key in keys:
            entry = _memory_holds.get(key)
            if entry is not None and entry[1] != ignore_token:
                held.add(key)
    return held


def extend_hold(slot_keys: list[str], token: str, ttl_seconds: Optional[int] = None) -> bool:
    """Renew the TTL on an existing hold the caller still owns, without minting a
    new token or briefly releasing the slot. Returns False if the token no longer
    owns every slot (e.g. it already expired)."""
    if not slot_keys:
        return False
    ttl_seconds = ttl_seconds or settings.RESERVATION_HOLD_MINUTES * 60
    keys = list(slot_keys)
    redis_client = _redis_client()
    if redis_client is not None:
        if any(value != token for value in redis_client.mget(keys)):
            return False
        pipeline = redis_client.pipeline()
        for key in keys:
            pipeline.expire(key, ttl_seconds)
        pipeline.execute()
        return True

    with _memory_lock:
        _cleanup_expired_memory_holds()
        if any(_memory_holds.get(key, (None, None))[1] != token for key in keys):
            return False
        new_expiry = time.time() + ttl_seconds
        for key in keys:
            _memory_holds[key] = (new_expiry, token)
    return True


def validate_hold(slot_keys: list[str], token: str) -> bool:
    redis_client = _redis_client()
    if redis_client is not None:
        return all(redis_client.get(slot_key) == token for slot_key in slot_keys)

    with _memory_lock:
        _cleanup_expired_memory_holds()
        return all(_memory_holds.get(slot_key, (None, None))[1] == token for slot_key in slot_keys)


def release_hold(slot_keys: list[str], token: str) -> None:
    redis_client = _redis_client()
    if redis_client is not None:
        pipeline = redis_client.pipeline()
        for slot_key in slot_keys:
            if redis_client.get(slot_key) == token:
                pipeline.delete(slot_key)
        pipeline.execute()
        return

    with _memory_lock:
        _cleanup_expired_memory_holds()
        for slot_key in slot_keys:
            if _memory_holds.get(slot_key, (None, None))[1] == token:
                _memory_holds.pop(slot_key, None)
