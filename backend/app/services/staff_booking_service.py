from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from math import floor
from secrets import choice
from string import ascii_uppercase, digits
from typing import Optional
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import create_access_token, hash_password
from app.models.booking import Booking
from app.models.staff_booking import StaffBooking
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.roles import user_has_admin_access
from app.schemas.staff_booking import (
    GuestStaffBookingCreate,
    GuestStaffBookingCreateOut,
    StaffBookingCreate,
    StaffBookingRescheduleIn,
)
from app.services.booking_service import (
    BOOKING_OPEN_WEEKDAYS,
    DailyBookingLimitError,
    PaymentSessionError,
    create_audit_log,
    create_notification_log,
    ensure_booking_start_not_in_past,
    ensure_single_booking_per_day,
    is_database_booking_conflict,
    is_booking_date_before_today,
)
from app.services.payment_service import (
    PaymentBackendError,
    create_payment_intent,
    create_refund,
    get_payment_intent_session,
)
from app.services.promo_code_service import apply_promo_code_to_amount


# A Requested or accepted booking holds the slot just like a paid one.
ACTIVE_BOOKING_STATUSES = ("Requested", "AcceptedPendingPayment", "PendingPayment", "Paid", "Completed")
# Bookings awaiting customer payment (new accepted flow + legacy PendingPayment).
PAYABLE_STATUSES = ("AcceptedPendingPayment", "PendingPayment")
AMBIGUOUS_CHARACTERS = {"0", "1", "I", "O"}
BOOKING_CODE_ALPHABET = "".join(
    character for character in f"{ascii_uppercase}{digits}" if character not in AMBIGUOUS_CHARACTERS
)


class StaffBookingConflictError(Exception):
    pass


class StaffBookingStateError(ValueError):
    """Raised when a booking isn't in the expected state for a transition."""


logger = logging.getLogger(__name__)


def _dispatch_staff_request_notifications(staff_booking_id) -> None:
    """Best-effort: enqueue the staff request email/SMS. Enqueue failures never
    break booking creation."""
    try:
        from app.tasks import (
            send_staff_booking_request_email_task,
            send_staff_booking_request_sms_task,
        )

        send_staff_booking_request_email_task.delay(str(staff_booking_id))
        send_staff_booking_request_sms_task.delay(str(staff_booking_id))
    except Exception:  # pragma: no cover - notification enqueue is best-effort
        logger.exception("Failed to enqueue staff request notifications for %s", staff_booking_id)


def _dispatch_staff_decision_notification(staff_booking_id, *, accepted: bool) -> None:
    try:
        if accepted:
            from app.tasks import send_staff_booking_accepted_customer_email_task as task_fn
        else:
            from app.tasks import send_staff_booking_declined_customer_email_task as task_fn
        task_fn.delay(str(staff_booking_id))
    except Exception:  # pragma: no cover - notification enqueue is best-effort
        logger.exception("Failed to enqueue staff decision notification for %s", staff_booking_id)


def get_business_timezone() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TIMEZONE)


def get_booking_window_hours() -> tuple[int, int]:
    return settings.BOOKING_OPEN_HOUR, settings.BOOKING_CLOSE_HOUR


def generate_booking_code(length: int = 8) -> str:
    return "".join(choice(BOOKING_CODE_ALPHABET) for _ in range(length))


def normalize_booking_start(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Booking times must include a timezone offset")
    utc_value = value.astimezone(timezone.utc)
    return utc_value.replace(second=0, microsecond=0)


def validate_booking_window(start_time: datetime, end_time: datetime) -> None:
    business_timezone = get_business_timezone()
    open_hour, close_hour = get_booking_window_hours()
    local_start = start_time.astimezone(business_timezone)
    local_end = end_time.astimezone(business_timezone)

    if local_start.minute != 0 or local_end.minute != 0:
        raise ValueError("Bookings must use one-hour increments")
    if local_start.date() != local_end.date():
        raise ValueError("Bookings must start and end on the same business day")
    if local_start.hour < open_hour or local_end.hour > close_hour:
        raise ValueError(f"Bookings are only available between {open_hour}:00 and {close_hour}:00")


def get_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    business_timezone = get_business_timezone()
    local_start = datetime.combine(target_date, time.min, tzinfo=business_timezone)
    local_end = local_start + timedelta(days=1)
    return local_start.astimezone(timezone.utc), local_end.astimezone(timezone.utc)


def calculate_price_cents(hourly_rate_cents: int, duration_minutes: int) -> int:
    return floor(hourly_rate_cents * (duration_minutes / 60))


def get_staff_profile_or_404(db: Session, staff_profile_id: UUID | str, include_inactive: bool = False) -> StaffProfile:
    profile = db.query(StaffProfile).filter(StaffProfile.id == staff_profile_id).first()
    if not profile or (not profile.active and not include_inactive):
        raise ValueError("Staff profile not found")
    if not profile.booking_enabled and not include_inactive:
        raise ValueError("Staff booking is not enabled for this profile")
    return profile


def get_staff_booking_rate_cents(profile: StaffProfile) -> int:
    return max(0, profile.booking_rate_cents or profile.add_on_price_cents or 0)


def attach_staff_profile_snapshot(
    db: Session,
    booking: StaffBooking,
    *,
    profile: Optional[StaffProfile] = None,
) -> StaffBooking:
    booking.staff_profile = profile or get_staff_profile_or_404(
        db,
        booking.staff_profile_id,
        include_inactive=True,
    )
    return booking


def normalize_service_type(profile: StaffProfile, service_type: Optional[str]) -> Optional[str]:
    if not service_type:
        return None
    normalized = service_type.strip()
    allowed = [item for item in (profile.service_types or []) if item]
    if allowed and normalized not in allowed:
        raise ValueError("Selected service type is not available for this staff profile")
    return normalized


def expire_pending_staff_booking(
    db: Session,
    booking: StaffBooking,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Expire a stale booking. A Requested booking past its 48h window becomes
    Expired; an accepted/legacy-pending booking past its payment window becomes
    Cancelled. Returns True if the status changed."""
    current_time = now or datetime.now(timezone.utc)
    if booking.status == "Requested":
        if not booking.request_expires_at or booking.request_expires_at > current_time:
            return False
        booking.status = "Expired"
        booking.responded_at = current_time
        booking.cancellation_reason = (
            f"Request expired after {settings.STAFF_REQUEST_EXPIRY_HOURS} hours with no response"
        )
        return True
    if booking.status in PAYABLE_STATUSES:
        if not booking.payment_expires_at or booking.payment_expires_at > current_time:
            return False
        booking.status = "Cancelled"
        booking.cancelled_at = current_time
        booking.cancellation_reason = (
            f"Payment window expired after {settings.PENDING_BOOKING_EXPIRY_MINUTES} minutes"
        )
        return True
    return False


def expire_stale_pending_staff_bookings(db: Session) -> int:
    stale_bookings = (
        db.query(StaffBooking)
        .filter(StaffBooking.status.in_(("Requested",) + PAYABLE_STATUSES))
        .all()
    )
    cleaned = 0
    for booking in stale_bookings:
        if expire_pending_staff_booking(db, booking):
            cleaned += 1
    if cleaned:
        db.commit()
    return cleaned


def ensure_staff_is_available(
    db: Session,
    staff_profile_id: UUID | str,
    start_time: datetime,
    end_time: datetime,
    *,
    exclude_staff_booking_id: UUID | str | None = None,
) -> None:
    overlapping_staff_bookings = (
        db.query(StaffBooking)
        .filter(StaffBooking.staff_profile_id == staff_profile_id)
        .filter(StaffBooking.start_time < end_time)
        .filter(StaffBooking.end_time > start_time)
        .filter(StaffBooking.status.in_(ACTIVE_BOOKING_STATUSES))
    )
    if exclude_staff_booking_id:
        overlapping_staff_bookings = overlapping_staff_bookings.filter(StaffBooking.id != exclude_staff_booking_id)
    if overlapping_staff_bookings.first():
        raise StaffBookingConflictError("Selected staff member is already booked for this time")

    overlapping_room_bookings = (
        db.query(Booking)
        .filter(Booking.start_time < end_time)
        .filter(Booking.end_time > start_time)
        .filter(Booking.status.in_(ACTIVE_BOOKING_STATUSES))
        .all()
    )
    profile_id = str(staff_profile_id)
    for booking in overlapping_room_bookings:
        for assignment in booking.staff_assignments or []:
            if str(assignment.get("id") or "") == profile_id:
                raise StaffBookingConflictError("Selected staff member is already assigned to a room booking at this time")


def _availability_windows_for_staff_date(
    db: Session,
    staff_profile_id: UUID | str,
    target_date: date,
) -> list[tuple[int, int]]:
    from app.services.staff_availability_service import (
        available_windows_for_date,
        has_availability_rules,
    )

    # Unpublished schedules aren't bookable by the public — the staff member is
    # still listed, but shows no available times until an admin publishes.
    published = (
        db.query(StaffProfile.schedule_published)
        .filter(StaffProfile.id == staff_profile_id)
        .scalar()
    )
    if not published:
        return []

    open_hour, close_hour = get_booking_window_hours()
    if has_availability_rules(db, staff_profile_id):
        return available_windows_for_date(db, staff_profile_id, target_date)

    base_windows = (
        [(open_hour * 60, close_hour * 60)]
        if target_date.weekday() in BOOKING_OPEN_WEEKDAYS
        else []
    )
    return available_windows_for_date(db, staff_profile_id, target_date, base_windows=base_windows)


def ensure_staff_window_is_available(
    db: Session,
    staff_profile_id: UUID | str,
    start_time: datetime,
    end_time: datetime,
) -> None:
    business_timezone = get_business_timezone()
    local_start = start_time.astimezone(business_timezone)
    local_end = end_time.astimezone(business_timezone)
    if local_start.date() != local_end.date():
        raise ValueError("Bookings must start and end on the same business day")

    start_minute = local_start.hour * 60 + local_start.minute
    end_minute = local_end.hour * 60 + local_end.minute
    windows = _availability_windows_for_staff_date(db, staff_profile_id, local_start.date())
    if not any(window_start <= start_minute and end_minute <= window_end for window_start, window_end in windows):
        raise ValueError("Selected staff member is not available for this time")


def get_staff_availability(db: Session, staff_profile_id: UUID | str, target_date: date) -> dict:
    expire_stale_pending_staff_bookings(db)
    get_staff_profile_or_404(db, staff_profile_id)
    business_timezone = get_business_timezone()
    open_hour, close_hour = get_booking_window_hours()
    utc_start, utc_end = get_day_bounds(target_date)

    availability_windows = _availability_windows_for_staff_date(db, staff_profile_id, target_date)
    available_start_times: list[str] = []
    max_duration_minutes_by_start: dict[str, int] = {}
    current_time = datetime.now(timezone.utc)

    if is_booking_date_before_today(target_date, now=current_time):
        return {
            "staff_profile_id": staff_profile_id,
            "date": target_date,
            "timezone": settings.BUSINESS_TIMEZONE,
            "available_start_times": [],
            "max_duration_minutes_by_start": {},
        }

    for local_hour in range(open_hour, close_hour):
        local_start = datetime.combine(target_date, time(hour=local_hour), tzinfo=business_timezone)
        start_time = local_start.astimezone(timezone.utc)
        if start_time < utc_start or start_time >= utc_end:
            continue
        if start_time <= current_time:
            continue

        slot_start_minute = local_hour * 60
        max_duration_minutes = 0
        for duration_minutes in range(60, 301, 60):
            end_time = start_time + timedelta(minutes=duration_minutes)
            if not any(
                window_start <= slot_start_minute and slot_start_minute + duration_minutes <= window_end
                for window_start, window_end in availability_windows
            ):
                break
            if end_time.astimezone(business_timezone).date() != target_date:
                break
            if end_time.astimezone(business_timezone).hour > close_hour:
                break
            try:
                ensure_staff_is_available(db, staff_profile_id, start_time, end_time)
            except StaffBookingConflictError:
                break
            max_duration_minutes = duration_minutes

        if max_duration_minutes >= 60:
            iso_value = local_start.isoformat()
            available_start_times.append(iso_value)
            max_duration_minutes_by_start[iso_value] = max_duration_minutes

    return {
        "staff_profile_id": staff_profile_id,
        "date": target_date,
        "timezone": settings.BUSINESS_TIMEZONE,
        "available_start_times": available_start_times,
        "max_duration_minutes_by_start": max_duration_minutes_by_start,
    }


def list_staff_bookings_for_user(db: Session, user: User) -> list[StaffBooking]:
    expire_stale_pending_staff_bookings(db)
    bookings = (
        db.query(StaffBooking)
        .filter(StaffBooking.user_id == user.id)
        .order_by(StaffBooking.start_time.desc())
        .all()
    )
    profile_ids = {booking.staff_profile_id for booking in bookings}
    profiles = {
        profile.id: profile
        for profile in db.query(StaffProfile).filter(StaffProfile.id.in_(profile_ids)).all()
    }
    return [attach_staff_profile_snapshot(db, booking, profile=profiles.get(booking.staff_profile_id)) for booking in bookings]


def list_staff_bookings_for_profile(db: Session, staff_profile_id, statuses=None) -> list[StaffBooking]:
    """Bookings for a staff member's own profile (for the staff portal)."""
    expire_stale_pending_staff_bookings(db)
    query = db.query(StaffBooking).filter(StaffBooking.staff_profile_id == staff_profile_id)
    if statuses:
        query = query.filter(StaffBooking.status.in_(tuple(statuses)))
    bookings = query.order_by(StaffBooking.start_time.asc()).all()
    profile = db.query(StaffProfile).filter(StaffProfile.id == staff_profile_id).first()
    return [attach_staff_profile_snapshot(db, booking, profile=profile) for booking in bookings]


def serialize_admin_staff_booking(
    booking: StaffBooking,
    *,
    user_email: Optional[str],
    user_full_name: Optional[str],
    user_phone: Optional[str],
    profile: Optional[StaffProfile],
) -> dict:
    staff_name = profile.name if profile else booking.service_type or "Staff booking"
    return {
        "id": booking.id,
        "booking_kind": "staff",
        "room_id": None,
        "staff_profile_id": booking.staff_profile_id,
        "user_id": booking.user_id,
        "start_time": booking.start_time,
        "end_time": booking.end_time,
        "duration_minutes": booking.duration_minutes,
        "original_price_cents": booking.original_price_cents,
        "discount_cents": booking.discount_cents,
        "promo_code": booking.promo_code,
        "price_cents": booking.price_cents,
        "currency": booking.currency,
        "status": booking.status,
        "booking_code": booking.booking_code,
        "payment_intent_id": booking.payment_intent_id,
        "payment_expires_at": booking.payment_expires_at,
        "payment_seconds_remaining": booking.payment_seconds_remaining,
        "confirmed_at": booking.confirmed_at,
        "checked_in_at": None,
        "cancelled_at": booking.cancelled_at,
        "cancellation_reason": booking.cancellation_reason,
        "note": booking.note,
        "staff_assignments": [],
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
        "user_email": booking.user_email_snapshot or user_email,
        "user_full_name": booking.user_full_name_snapshot or user_full_name,
        "user_phone": booking.user_phone_snapshot or user_phone,
        "room_name": None,
        "staff_name": staff_name,
        "staff_photo_url": profile.photo_url if profile else None,
        "service_type": booking.service_type,
        "location_label": "Staff support session",
    }


def list_staff_bookings_for_admin(
    db: Session,
    *,
    status: Optional[str] = None,
    email: Optional[str] = None,
    booking_code: Optional[str] = None,
) -> list[dict]:
    expire_stale_pending_staff_bookings(db)
    query = (
        db.query(
            StaffBooking,
            User.email,
            User.full_name,
            User.phone,
            StaffProfile,
        )
        .outerjoin(User, StaffBooking.user_id == User.id)
        .outerjoin(StaffProfile, StaffBooking.staff_profile_id == StaffProfile.id)
    )
    if status:
        query = query.filter(StaffBooking.status == status)
    if email:
        query = query.filter(
            (User.email.ilike(f"%{email}%"))
            | (StaffBooking.user_email_snapshot.ilike(f"%{email}%"))
        )
    if booking_code:
        query = query.filter(StaffBooking.booking_code == booking_code)

    results = query.order_by(StaffBooking.start_time.desc()).all()
    return [
        serialize_admin_staff_booking(
            booking,
            user_email=user_email,
            user_full_name=user_full_name,
            user_phone=user_phone,
            profile=profile,
        )
        for booking, user_email, user_full_name, user_phone, profile in results
    ]


def get_staff_booking_for_user(db: Session, staff_booking_id: UUID | str, user: User) -> Optional[StaffBooking]:
    expire_stale_pending_staff_bookings(db)
    query = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id)
    if not user_has_admin_access(user):
        query = query.filter(StaffBooking.user_id == user.id)
    booking = query.first()
    if not booking:
        return None
    return attach_staff_profile_snapshot(db, booking)


def update_staff_booking_contact(db: Session, booking: StaffBooking, user: User, payload) -> StaffBooking:
    previous = {
        "full_name": booking.user_full_name_snapshot,
        "email": booking.user_email_snapshot,
        "phone": booking.user_phone_snapshot,
        "note": booking.note,
    }
    next_values = {
        "full_name": payload.full_name,
        "email": payload.email,
        "phone": payload.phone,
        "note": payload.note,
    }
    booking.user_full_name_snapshot = payload.full_name
    booking.user_email_snapshot = payload.email
    booking.user_phone_snapshot = payload.phone
    booking.note = payload.note
    create_audit_log(
        db,
        actor_id=user.id,
        booking_id=None,
        action="staff_booking_contact_updated",
        details={
            "staff_booking_id": str(booking.id),
            "changed_fields": [
                field for field, old_value in previous.items() if old_value != next_values[field]
            ],
        },
    )
    db.commit()
    db.refresh(booking)
    return attach_staff_profile_snapshot(db, booking)


def _create_staff_booking_record(
    db: Session,
    *,
    profile: StaffProfile,
    user: User,
    service_type: Optional[str],
    start_time: datetime,
    duration_minutes: int,
    promo_code: Optional[str],
    note: Optional[str],
    enforce_daily_limit: bool,
) -> StaffBooking:
    expire_stale_pending_staff_bookings(db)
    normalized_start = normalize_booking_start(start_time)
    ensure_booking_start_not_in_past(normalized_start)
    end_time = normalized_start + timedelta(minutes=duration_minutes)
    validate_booking_window(normalized_start, end_time)
    ensure_staff_window_is_available(db, profile.id, normalized_start, end_time)
    if enforce_daily_limit:
        ensure_single_booking_per_day(db, user, normalized_start, duration_minutes)
    ensure_staff_is_available(db, profile.id, normalized_start, end_time)
    original_price_cents = calculate_price_cents(get_staff_booking_rate_cents(profile), duration_minutes)
    promo_result = apply_promo_code_to_amount(db, promo_code, original_price_cents, user)

    booking = StaffBooking(
        user_id=user.id,
        staff_profile_id=profile.id,
        service_type=normalize_service_type(profile, service_type),
        start_time=normalized_start,
        end_time=end_time,
        duration_minutes=duration_minutes,
        original_price_cents=original_price_cents,
        discount_cents=promo_result["discount_cents"],
        promo_code=promo_result["promo_code"].code if promo_result["promo_code"] else None,
        price_cents=promo_result["final_amount_cents"],
        currency=settings.DEFAULT_CURRENCY,
        # Request-first: the booking starts as a request and is only charged
        # once the staff member accepts (see accept_staff_booking).
        status="Requested",
        booking_code=generate_booking_code(),
        user_email_snapshot=user.email,
        user_full_name_snapshot=user.full_name,
        user_phone_snapshot=user.phone,
        note=note,
    )

    try:
        db.add(booking)
        db.commit()
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        if not is_database_booking_conflict(exc):
            raise
        raise StaffBookingConflictError("Selected time is no longer available") from exc

    db.refresh(booking)
    attach_staff_profile_snapshot(db, booking, profile=profile)
    create_notification_log(
        db,
        user_id=user.id,
        booking_id=None,
        notification_type="staff_booking_requested",
        status="Queued",
        details={
            "staff_booking_id": str(booking.id),
            "booking_code": booking.booking_code,
            "promo_code": booking.promo_code,
            "discount_cents": booking.discount_cents,
        },
    )
    create_audit_log(
        db,
        actor_id=user.id,
        booking_id=None,
        action="staff_booking_created",
        details={
            "staff_booking_id": str(booking.id),
            "staff_profile_id": str(profile.id),
        },
    )
    db.commit()
    _dispatch_staff_request_notifications(booking.id)
    return booking


def create_staff_booking(db: Session, user: User, payload: StaffBookingCreate) -> StaffBooking:
    profile = get_staff_profile_or_404(db, payload.staff_profile_id)
    return _create_staff_booking_record(
        db,
        profile=profile,
        user=user,
        service_type=payload.service_type,
        start_time=payload.start_time,
        duration_minutes=payload.duration_minutes,
        promo_code=payload.promo_code,
        note=payload.note,
        enforce_daily_limit=not user_has_admin_access(user),
    )


def create_guest_staff_booking(db: Session, payload: GuestStaffBookingCreate) -> GuestStaffBookingCreateOut:
    profile = get_staff_profile_or_404(db, payload.staff_profile_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    guest_email = (
        payload.guest_email.strip()
        if payload.guest_email
        else f"guest+{timestamp}-{uuid4().hex[:8]}@guest.studiobooking.local"
    )
    guest_user = User(
        email=guest_email,
        password_hash=hash_password(uuid4().hex),
        full_name=payload.guest_name.strip(),
        phone=payload.guest_phone.strip(),
    )
    db.add(guest_user)
    db.flush()
    booking = _create_staff_booking_record(
        db,
        profile=profile,
        user=guest_user,
        service_type=payload.service_type,
        start_time=payload.start_time,
        duration_minutes=payload.duration_minutes,
        promo_code=payload.promo_code,
        note=payload.note,
        enforce_daily_limit=True,
    )
    token = create_access_token({"sub": str(guest_user.id)})
    return GuestStaffBookingCreateOut(access_token=token, booking=booking)


def accept_staff_booking(db: Session, booking: StaffBooking, *, actor_id: UUID | str | None = None) -> StaffBooking:
    """Staff accepts a request: generate the payment intent and move it to
    AcceptedPendingPayment so the customer can pay."""
    expire_stale_pending_staff_bookings(db)
    db.refresh(booking)
    if booking.status != "Requested":
        raise StaffBookingStateError("This booking request is no longer pending a response")

    try:
        payment_intent = create_payment_intent(
            amount_cents=booking.price_cents,
            currency=booking.currency,
            booking_id=str(booking.id),
            user_email=booking.user_email_snapshot or "",
            metadata={"booking_type": "staff", "staff_booking_id": str(booking.id)},
        )
    except PaymentBackendError:
        db.rollback()
        raise

    booking.payment_intent_id = payment_intent.intent_id
    booking.payment_client_secret = payment_intent.client_secret
    booking.status = "AcceptedPendingPayment"
    booking.responded_at = datetime.now(timezone.utc)
    create_notification_log(
        db,
        user_id=booking.user_id,
        booking_id=None,
        notification_type="staff_booking_accepted",
        status="Queued",
        details={"staff_booking_id": str(booking.id), "booking_code": booking.booking_code},
    )
    create_audit_log(
        db,
        actor_id=actor_id,
        booking_id=None,
        action="staff_booking_accepted",
        details={"staff_booking_id": str(booking.id)},
    )
    db.commit()
    db.refresh(booking)
    _dispatch_staff_decision_notification(booking.id, accepted=True)
    return attach_staff_profile_snapshot(db, booking)


def decline_staff_booking(
    db: Session, booking: StaffBooking, *, reason: Optional[str] = None, actor_id: UUID | str | None = None
) -> StaffBooking:
    """Staff declines a request: release the slot and notify the customer."""
    expire_stale_pending_staff_bookings(db)
    db.refresh(booking)
    if booking.status != "Requested":
        raise StaffBookingStateError("This booking request is no longer pending a response")

    booking.status = "Declined"
    booking.responded_at = datetime.now(timezone.utc)
    booking.cancellation_reason = (reason or "").strip() or "Declined by staff"
    create_notification_log(
        db,
        user_id=booking.user_id,
        booking_id=None,
        notification_type="staff_booking_declined",
        status="Queued",
        details={"staff_booking_id": str(booking.id), "reason": booking.cancellation_reason},
    )
    create_audit_log(
        db,
        actor_id=actor_id,
        booking_id=None,
        action="staff_booking_declined",
        details={"staff_booking_id": str(booking.id), "reason": booking.cancellation_reason},
    )
    db.commit()
    db.refresh(booking)
    _dispatch_staff_decision_notification(booking.id, accepted=False)
    return attach_staff_profile_snapshot(db, booking)


def get_staff_booking_payment_session(db: Session, booking: StaffBooking, user: User) -> dict:
    expire_stale_pending_staff_bookings(db)
    if booking.status not in PAYABLE_STATUSES:
        raise PaymentSessionError("Payment session is only available once a request is accepted")
    if expire_pending_staff_booking(db, booking):
        db.commit()
        raise PaymentSessionError("Payment window expired for this booking")
    payment_session = get_payment_intent_session(
        payment_intent_id=booking.payment_intent_id,
        amount_cents=booking.price_cents,
        currency=booking.currency,
        booking_id=str(booking.id),
        user_email=user.email or booking.user_email_snapshot or "",
        metadata={
            "booking_type": "staff",
            "staff_booking_id": str(booking.id),
        },
    )
    if booking.payment_intent_id != payment_session.intent_id:
        booking.payment_intent_id = payment_session.intent_id
        booking.payment_client_secret = payment_session.client_secret
        db.commit()
        db.refresh(booking)
    attach_staff_profile_snapshot(db, booking)
    return {
        "booking_id": booking.id,
        "payment_intent_id": payment_session.intent_id,
        "payment_client_secret": payment_session.client_secret,
        "payment_backend": settings.PAYMENT_BACKEND,
        "stripe_publishable_key": settings.STRIPE_PUBLISHABLE_KEY,
        "payment_expires_at": booking.payment_expires_at,
        "payment_seconds_remaining": booking.payment_seconds_remaining,
    }


def waive_staff_booking_payment(db: Session, booking: StaffBooking, admin: User) -> StaffBooking:
    if booking.status not in PAYABLE_STATUSES:
        raise ValueError("Only accepted staff bookings awaiting payment can skip Stripe payment")
    original_price_cents = booking.price_cents
    booking.price_cents = 0
    waived_payment_reference = f"admin_staff_waived_{uuid4().hex[:20]}"
    booking = mark_staff_booking_paid(db, booking, waived_payment_reference)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="staff_booking_payment_waived_by_admin",
        details={
            "staff_booking_id": str(booking.id),
            "original_price_cents": original_price_cents,
            "payment_intent_id": waived_payment_reference,
            "reason": "Admin skipped Stripe payment for staff booking",
        },
    )
    db.commit()
    db.refresh(booking)
    return attach_staff_profile_snapshot(db, booking)


def cancel_staff_booking(db: Session, booking: StaffBooking, user: User, reason: Optional[str] = None) -> StaffBooking:
    if booking.status not in ("Requested", "AcceptedPendingPayment", "PendingPayment", "Paid"):
        raise ValueError("Only active staff bookings can be cancelled")
    booking.status = "Cancelled"
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.cancellation_reason = reason or "Cancelled by user"
    create_audit_log(
        db,
        actor_id=user.id,
        booking_id=None,
        action="staff_booking_cancelled",
        details={
            "staff_booking_id": str(booking.id),
            "reason": booking.cancellation_reason,
        },
    )
    db.commit()
    db.refresh(booking)
    return attach_staff_profile_snapshot(db, booking)


def reschedule_staff_booking(
    db: Session,
    booking: StaffBooking,
    user: User,
    payload: StaffBookingRescheduleIn,
) -> StaffBooking:
    if booking.status not in ("Requested", "AcceptedPendingPayment", "PendingPayment", "Paid"):
        raise ValueError("Only active staff bookings can be rescheduled")
    normalized_start = normalize_booking_start(payload.start_time)
    ensure_booking_start_not_in_past(normalized_start)
    end_time = normalized_start + timedelta(minutes=booking.duration_minutes)
    validate_booking_window(normalized_start, end_time)
    ensure_staff_window_is_available(db, booking.staff_profile_id, normalized_start, end_time)
    limit_user = user
    if booking.user_id and booking.user_id != user.id:
        owner = db.query(User).filter(User.id == booking.user_id).first()
        if owner:
            limit_user = owner
    if not user_has_admin_access(limit_user):
        ensure_single_booking_per_day(
            db,
            limit_user,
            normalized_start,
            booking.duration_minutes,
            exclude_staff_booking_id=booking.id,
        )
    ensure_staff_is_available(
        db,
        booking.staff_profile_id,
        normalized_start,
        end_time,
        exclude_staff_booking_id=booking.id,
    )
    try:
        booking.start_time = normalized_start
        booking.end_time = end_time
        create_audit_log(
            db,
            actor_id=user.id,
            booking_id=None,
            action="staff_booking_rescheduled",
            details={
                "staff_booking_id": str(booking.id),
                "new_start_time": normalized_start.isoformat(),
            },
        )
        db.commit()
    except (IntegrityError, OperationalError) as exc:
        db.rollback()
        if not is_database_booking_conflict(exc):
            raise
        raise StaffBookingConflictError("Selected time is no longer available") from exc
    db.refresh(booking)
    return attach_staff_profile_snapshot(db, booking)


def mark_staff_booking_paid(db: Session, booking: StaffBooking, payment_intent_id: str) -> StaffBooking:
    if booking.status not in PAYABLE_STATUSES:
        raise ValueError("Only accepted staff bookings awaiting payment can be marked paid")
    booking.status = "Paid"
    booking.payment_intent_id = payment_intent_id
    booking.confirmed_at = datetime.now(timezone.utc)
    create_notification_log(
        db,
        user_id=booking.user_id,
        booking_id=None,
        notification_type="staff_booking_confirmation",
        status="Sent",
        details={"staff_booking_id": str(booking.id), "payment_intent_id": payment_intent_id},
    )
    create_audit_log(
        db,
        actor_id=None,
        booking_id=None,
        action="staff_booking_payment_confirmed",
        details={"staff_booking_id": str(booking.id), "payment_intent_id": payment_intent_id},
    )
    db.commit()
    db.refresh(booking)
    return attach_staff_profile_snapshot(db, booking)


def mark_staff_booking_paid_manually(db: Session, booking: StaffBooking, admin: User) -> StaffBooking:
    if booking.status not in PAYABLE_STATUSES:
        raise ValueError("Only accepted staff bookings awaiting payment can be marked paid manually")
    manual_payment_reference = f"admin_staff_manual_paid_{uuid4().hex[:20]}"
    booking = mark_staff_booking_paid(db, booking, manual_payment_reference)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="staff_booking_marked_paid_by_admin",
        details={
            "staff_booking_id": str(booking.id),
            "price_cents": booking.price_cents,
            "payment_intent_id": manual_payment_reference,
            "reason": "Admin marked staff booking paid without Stripe checkout",
        },
    )
    db.commit()
    db.refresh(booking)
    return attach_staff_profile_snapshot(db, booking)


def _auto_refund_stale_staff_payment(
    db: Session,
    booking: StaffBooking,
    payment_intent_id: Optional[str],
) -> None:
    refund_amount = booking.price_cents or 0
    refund_id: Optional[str] = None
    failure_message: Optional[str] = None
    if payment_intent_id and refund_amount > 0:
        try:
            refund_id = create_refund(
                payment_intent_id=payment_intent_id,
                amount_cents=refund_amount,
            )
        except Exception as exc:  # noqa: BLE001
            failure_message = str(exc)
    create_audit_log(
        db,
        actor_id=None,
        booking_id=None,
        action="staff_payment_received_after_expiry",
        details={
            "staff_booking_id": str(booking.id),
            "payment_intent_id": payment_intent_id,
            "booking_status": booking.status,
            "amount_cents": refund_amount,
            "stripe_refund_id": refund_id,
            "refund_error": failure_message,
        },
    )
    db.commit()


def handle_staff_booking_payment_webhook_event(db: Session, event: dict) -> dict:
    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})
    payment_intent_id = data_object.get("id")
    metadata = data_object.get("metadata", {}) or {}
    staff_booking_id = metadata.get("staff_booking_id")

    booking = None
    if staff_booking_id:
        booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
    if not booking and payment_intent_id:
        booking = db.query(StaffBooking).filter(StaffBooking.payment_intent_id == payment_intent_id).first()
    if not booking:
        raise ValueError("Staff booking not found for webhook event")

    if event_type == "payment_intent.succeeded":
        if booking.status == "Paid":
            return {"received": True, "staff_booking_id": str(booking.id), "status": booking.status}
        if booking.status not in PAYABLE_STATUSES:
            _auto_refund_stale_staff_payment(db, booking, payment_intent_id)
            return {
                "received": True,
                "ignored": True,
                "auto_refunded": True,
                "staff_booking_id": str(booking.id),
                "status": booking.status,
            }
        if expire_pending_staff_booking(db, booking):
            db.commit()
            _auto_refund_stale_staff_payment(db, booking, payment_intent_id)
            return {
                "received": True,
                "ignored": True,
                "auto_refunded": True,
                "staff_booking_id": str(booking.id),
                "status": booking.status,
            }
        updated = mark_staff_booking_paid(db, booking, payment_intent_id)
        return {"received": True, "staff_booking_id": str(updated.id), "status": updated.status}

    if event_type == "payment_intent.payment_failed":
        booking.status = "Cancelled"
        booking.cancelled_at = datetime.now(timezone.utc)
        booking.cancellation_reason = "Payment failed"
        create_audit_log(
            db,
            actor_id=None,
            booking_id=None,
            action="staff_booking_payment_failed",
            details={"staff_booking_id": str(booking.id), "payment_intent_id": payment_intent_id},
        )
        db.commit()
        return {"received": True, "staff_booking_id": str(booking.id), "status": booking.status}

    if event_type == "charge.refunded":
        booking.status = "Refunded"
        db.commit()
        return {"received": True, "staff_booking_id": str(booking.id), "status": booking.status}

    return {"received": True, "ignored": True}


def build_staff_booking_feed_item(booking: StaffBooking, *, profile: Optional[StaffProfile] = None) -> dict:
    profile = profile or getattr(booking, "staff_profile", None)
    title = (profile.name if profile else None) or booking.service_type or "Staff booking"
    subtitle = booking.service_type if booking.service_type and booking.service_type != title else None
    staff_profile_data = (
        {
            "id": str(profile.id),
            "name": profile.name,
            "description": profile.description,
            "photo_url": profile.photo_url,
            "skills": profile.skills or [],
            "talents": profile.talents or [],
            "booking_rate_cents": profile.booking_rate_cents,
            "service_types": profile.service_types or [],
            "booking_enabled": profile.booking_enabled,
            "active": profile.active,
        }
        if profile
        else None
    )
    return {
        "id": booking.id,
        "booking_kind": "staff",
        "staff_profile_id": booking.staff_profile_id,
        "staff_profile_name": profile.name if profile else title,
        "staff_name": title,
        "staff_photo_url": profile.photo_url if profile else None,
        "service_type": booking.service_type,
        "title": title,
        "subtitle": subtitle,
        "status": booking.status,
        "start_time": booking.start_time,
        "end_time": booking.end_time,
        "duration_minutes": booking.duration_minutes,
        "price_cents": booking.price_cents,
        "currency": booking.currency,
        "payment_intent_id": booking.payment_intent_id,
        "payment_client_secret": booking.payment_client_secret,
        "payment_expires_at": booking.payment_expires_at,
        "payment_seconds_remaining": booking.payment_seconds_remaining,
        "confirmed_at": booking.confirmed_at,
        "cancelled_at": booking.cancelled_at,
        "cancellation_reason": booking.cancellation_reason,
        "note": booking.note,
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
        "location_label": "Studio support session",
        "request_expires_at": booking.request_expires_at,
        "awaiting_approval": booking.status == "Requested",
        "can_cancel": booking.status in ("Requested", "AcceptedPendingPayment", "PendingPayment", "Paid"),
        "can_pay": booking.status in PAYABLE_STATUSES,
        "staff_profile": staff_profile_data,
    }
