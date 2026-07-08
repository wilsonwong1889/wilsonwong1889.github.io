from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.booking import Booking
from app.models.membership import UserMembership
from app.models.promo_code import PromoCode
from app.models.staff_booking import StaffBooking
from app.models.user import User
from app.schemas.promo_code import PromoCodeCreate, PromoCodeUpdate, normalize_promo_code


class PromoCodeError(ValueError):
    pass


# Short, human-friendly prefixes per scoped membership category.
_CATEGORY_CODE_PREFIX = {
    "artist_member": "ARTIST",
    "venture_member": "VENTURE",
}


def _user_membership_category(db: Session, user: User | None) -> str | None:
    if user is None:
        return None
    membership = (
        db.query(UserMembership)
        .filter(UserMembership.user_id == user.id)
        .order_by(UserMembership.created_at.desc())
        .first()
    )
    return membership.category if membership else None


def get_promo_code_by_code(db: Session, code: str) -> PromoCode | None:
    normalized_code = normalize_promo_code(code)
    return db.query(PromoCode).filter(PromoCode.code == normalized_code).first()


def list_promo_codes(db: Session) -> list[dict]:
    promo_codes = db.query(PromoCode).order_by(PromoCode.created_at.desc(), PromoCode.code.asc()).all()
    return [serialize_promo_code(db, promo_code) for promo_code in promo_codes]


def create_promo_code(db: Session, payload: PromoCodeCreate) -> dict:
    _validate_discount_shape(payload.percent_off, payload.amount_off_cents)
    existing = db.query(PromoCode).filter(PromoCode.code == payload.code).first()
    if existing:
        raise PromoCodeError("Promo code already exists")

    promo_code = PromoCode(**payload.model_dump())
    db.add(promo_code)
    db.flush()
    return serialize_promo_code(db, promo_code)


def update_promo_code(db: Session, promo_code_id: str, payload: PromoCodeUpdate) -> dict:
    promo_code = db.query(PromoCode).filter(PromoCode.id == promo_code_id).first()
    if not promo_code:
        raise PromoCodeError("Promo code not found")

    update_data = payload.model_dump(exclude_unset=True)
    percent_off = update_data.get("percent_off", promo_code.percent_off)
    amount_off_cents = update_data.get("amount_off_cents", promo_code.amount_off_cents)
    if ("percent_off" in update_data) or ("amount_off_cents" in update_data):
        _validate_discount_shape(percent_off, amount_off_cents)

    if "code" in update_data and update_data["code"] != promo_code.code:
        existing = db.query(PromoCode).filter(PromoCode.code == update_data["code"]).first()
        if existing:
            raise PromoCodeError("Promo code already exists")

    expires_at = update_data.get("expires_at", promo_code.expires_at)
    starts_at = update_data.get("starts_at", promo_code.starts_at)
    if expires_at and starts_at and expires_at <= starts_at:
        raise PromoCodeError("Promo code expiry must be after the start time")

    for field, value in update_data.items():
        setattr(promo_code, field, value)

    db.flush()
    return serialize_promo_code(db, promo_code)


def serialize_promo_code(db: Session, promo_code: PromoCode) -> dict:
    room_redemptions = (
        db.query(Booking)
        .filter(Booking.promo_code == promo_code.code)
        .filter(Booking.status.in_(("PendingPayment", "Paid", "DepositPaid", "Completed", "Refunded")))
        .count()
    )
    staff_redemptions = (
        db.query(StaffBooking)
        .filter(StaffBooking.promo_code == promo_code.code)
        .filter(StaffBooking.status.in_(("PendingPayment", "Paid", "Completed", "Refunded")))
        .count()
    )
    active_redemptions = room_redemptions + staff_redemptions
    return {
        "id": promo_code.id,
        "code": promo_code.code,
        "description": promo_code.description,
        "percent_off": promo_code.percent_off,
        "amount_off_cents": promo_code.amount_off_cents,
        "active": promo_code.active,
        "max_redemptions": promo_code.max_redemptions,
        "starts_at": promo_code.starts_at,
        "expires_at": promo_code.expires_at,
        "member_category": promo_code.member_category,
        "member_unique": bool(promo_code.member_unique),
        "assigned_user_id": promo_code.assigned_user_id,
        "valid_month": promo_code.valid_month,
        "active_redemptions": active_redemptions,
        "created_at": promo_code.created_at,
        "updated_at": promo_code.updated_at,
    }


def calculate_discount_for_amount(
    db: Session, code: str, amount_cents: int, user: User | None = None
) -> dict:
    if amount_cents < 0:
        raise PromoCodeError("Amount must be zero or higher")

    promo_code = get_promo_code_by_code(db, code)
    if not promo_code:
        raise PromoCodeError("Promo code not found")
    _ensure_promo_code_is_usable(db, promo_code, user)

    discount_cents = _calculate_discount_cents(promo_code, amount_cents)
    return {
        "promo_code": promo_code,
        "discount_cents": discount_cents,
        "final_amount_cents": max(amount_cents - discount_cents, 0),
    }


def apply_promo_code_to_amount(
    db: Session, code: str | None, amount_cents: int, user: User | None = None
) -> dict:
    if not code:
        return {"promo_code": None, "discount_cents": 0, "final_amount_cents": amount_cents}

    result = calculate_discount_for_amount(db, code, amount_cents, user)
    return result


def _ensure_promo_code_is_usable(db: Session, promo_code: PromoCode, user: User | None = None) -> None:
    now = datetime.now(timezone.utc)
    if not promo_code.active:
        raise PromoCodeError("Promo code is inactive")
    if promo_code.starts_at and promo_code.starts_at > now:
        raise PromoCodeError("Promo code is not active yet")
    if promo_code.expires_at and promo_code.expires_at < now:
        raise PromoCodeError("Promo code has expired")

    # Membership scoping. A personal (assigned) code is the strongest gate —
    # only its owner can redeem it. Otherwise a category-scoped code requires a
    # matching membership. (Codes do not stack: a booking carries one code.)
    if promo_code.assigned_user_id is not None:
        if user is None or str(user.id) != str(promo_code.assigned_user_id):
            raise PromoCodeError("This promo code is reserved for a specific member.")
    elif promo_code.member_category:
        if _user_membership_category(db, user) != promo_code.member_category:
            raise PromoCodeError("This promo code requires a matching membership.")
    if promo_code.max_redemptions is not None:
        room_redemptions = (
            db.query(Booking)
            .filter(Booking.promo_code == promo_code.code)
            .filter(Booking.status.in_(("PendingPayment", "Paid", "DepositPaid", "Completed", "Refunded")))
            .count()
        )
        staff_redemptions = (
            db.query(StaffBooking)
            .filter(StaffBooking.promo_code == promo_code.code)
            .filter(StaffBooking.status.in_(("PendingPayment", "Paid", "Completed", "Refunded")))
            .count()
        )
        active_redemptions = room_redemptions + staff_redemptions
        if active_redemptions >= promo_code.max_redemptions:
            raise PromoCodeError("Promo code has reached its usage limit")


def _calculate_discount_cents(promo_code: PromoCode, amount_cents: int) -> int:
    if amount_cents <= 0:
        return 0
    if promo_code.percent_off is not None:
        return min(amount_cents, round(amount_cents * (promo_code.percent_off / 100)))
    if promo_code.amount_off_cents is not None:
        return min(amount_cents, promo_code.amount_off_cents)
    return 0


def _validate_discount_shape(percent_off: int | None, amount_off_cents: int | None) -> None:
    if bool(percent_off) == bool(amount_off_cents):
        raise PromoCodeError("Choose exactly one discount type: percent or fixed amount")


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    """(start, end_exclusive) UTC datetimes for a 'YYYY-MM' month string."""
    try:
        year, mon = (int(part) for part in month.split("-"))
        start = datetime(year, mon, 1, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise PromoCodeError("month must be in YYYY-MM format")
    if mon == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, mon + 1, 1, tzinfo=timezone.utc)
    return start, end


def _generate_unique_code(db: Session, prefix: str, month_compact: str) -> str:
    for _ in range(25):
        candidate = f"{prefix}{month_compact}-{secrets.token_hex(3).upper()}"
        if not db.query(PromoCode).filter(PromoCode.code == candidate).first():
            return candidate
    raise PromoCodeError("Could not generate a unique promo code; please retry")


def _code_prefix_from_name(full_name: str) -> str:
    """A short, human-recognisable code prefix built from the person's name,
    e.g. 'Sarah Khan' -> 'SARAHKHAN' (capped)."""
    letters = re.sub(r"[^A-Za-z]", "", full_name).upper()
    return letters[:10] or "MEMBER"


def _generate_member_code(db: Session, prefix: str) -> str:
    for _ in range(25):
        candidate = f"{prefix}-{secrets.token_hex(3).upper()}"
        if not db.query(PromoCode).filter(PromoCode.code == candidate).first():
            return candidate
    raise PromoCodeError("Could not generate a unique promo code; please retry")


def create_member_code(
    db: Session, *, full_name: str, percent_off: int, max_uses: int | None = None
) -> dict:
    """Issue a single named discount code to someone who paid for a membership.
    The code is auto-generated from their name, gives percent_off, and is capped
    at max_uses redemptions (None = unlimited). It is not tied to a member
    account, so the person can redeem it by simply entering the code."""
    if not (1 <= percent_off <= 100):
        raise PromoCodeError("percent_off must be between 1 and 100")
    if max_uses is not None and max_uses < 1:
        raise PromoCodeError("max_uses must be at least 1, or leave it blank for unlimited")

    clean_name = " ".join(str(full_name or "").split())
    if not clean_name:
        raise PromoCodeError("Full name is required")

    promo = PromoCode(
        code=_generate_member_code(db, _code_prefix_from_name(clean_name)),
        description=f"Membership code — {clean_name}",
        percent_off=percent_off,
        max_redemptions=max_uses,
        member_unique=False,
        active=True,
    )
    db.add(promo)
    db.flush()
    return serialize_promo_code(db, promo)


def generate_monthly_member_codes(
    db: Session, *, month: str, member_category: str, percent_off: int = 50
) -> dict:
    """Create one unique, single-use, personal promo code per member in a
    category for the given month. Idempotent: members who already have a code
    for that month + category are skipped."""
    if not (1 <= percent_off <= 100):
        raise PromoCodeError("percent_off must be between 1 and 100")
    start, end = _month_bounds(month)
    month_compact = month.replace("-", "")
    prefix = _CATEGORY_CODE_PREFIX.get(member_category, member_category.upper().replace("_", "")[:8])

    members = (
        db.query(User)
        .join(UserMembership, UserMembership.user_id == User.id)
        .filter(UserMembership.category == member_category)
        .all()
    )
    # Dedupe in case a member has multiple membership rows in the category.
    unique_members = {member.id: member for member in members}.values()

    created: list[dict] = []
    skipped = 0
    for member in unique_members:
        existing = (
            db.query(PromoCode)
            .filter(PromoCode.assigned_user_id == member.id)
            .filter(PromoCode.valid_month == month)
            .filter(PromoCode.member_category == member_category)
            .first()
        )
        if existing:
            skipped += 1
            continue
        promo = PromoCode(
            code=_generate_unique_code(db, prefix, month_compact),
            description=f"{percent_off}% off for {member_category} — {month}",
            percent_off=percent_off,
            member_category=member_category,
            member_unique=True,
            assigned_user_id=member.id,
            valid_month=month,
            max_redemptions=1,
            starts_at=start,
            expires_at=end,
            active=True,
        )
        db.add(promo)
        db.flush()
        created.append(serialize_promo_code(db, promo))

    return {
        "month": month,
        "member_category": member_category,
        "percent_off": percent_off,
        "created": len(created),
        "skipped": skipped,
        "codes": created,
    }
