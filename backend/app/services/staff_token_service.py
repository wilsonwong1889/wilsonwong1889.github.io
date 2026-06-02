from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models.staff_booking_token import StaffBookingResponseToken


class StaffTokenError(ValueError):
    """Raised when an accept/decline token is missing, invalid, used, or expired."""


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_response_token(db: Session, booking) -> str:
    """Mint a one-time accept/decline token for a booking and store only its
    hash. Returns the raw token (to embed in the staff's link); it is never
    persisted in plaintext."""
    raw_token = secrets.token_urlsafe(32)
    token = StaffBookingResponseToken(
        staff_booking_id=booking.id,
        token_hash=_hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=settings.STAFF_REQUEST_EXPIRY_HOURS),
    )
    db.add(token)
    db.flush()
    return raw_token


def resolve_response_token(db: Session, staff_booking_id, raw_token: str | None) -> StaffBookingResponseToken:
    if not raw_token:
        raise StaffTokenError("A response token is required")
    token = (
        db.query(StaffBookingResponseToken)
        .filter(
            StaffBookingResponseToken.staff_booking_id == staff_booking_id,
            StaffBookingResponseToken.token_hash == _hash_token(raw_token),
        )
        .first()
    )
    if not token:
        raise StaffTokenError("This response link is invalid")
    if token.used_at is not None:
        raise StaffTokenError("This response link has already been used")
    expires_at = token.expires_at
    if expires_at.tzinfo is None or expires_at.utcoffset() is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise StaffTokenError("This response link has expired")
    return token


def mark_token_used(token: StaffBookingResponseToken) -> None:
    token.used_at = datetime.now(timezone.utc)
