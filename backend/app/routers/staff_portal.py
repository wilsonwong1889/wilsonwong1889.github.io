"""Staff self-service portal: a staff member manages their own schedule and
responds to their own booking requests in-app (no email/SMS required)."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.dependencies import get_staff_user
from app.database import get_db
from app.models.staff_booking import StaffBooking
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.schemas.staff import StaffProfileOut
from app.schemas.staff_availability import (
    StaffAvailabilityExceptionCreate,
    StaffAvailabilityExceptionOut,
    StaffAvailabilityRuleCreate,
    StaffAvailabilityRuleOut,
)
from app.schemas.staff_booking import StaffBookingCancel, StaffBookingOut
from app.services import staff_availability_service as availability
from app.services.payment_service import PaymentBackendError
from app.services.staff_booking_service import (
    StaffBookingConflictError,
    StaffBookingStateError,
    accept_staff_booking,
    decline_staff_booking,
    list_staff_bookings_for_profile,
)
from app.services.staff_service import get_staff_profile_for_user

router = APIRouter(prefix="/api/staff/me", tags=["Staff Portal"])


def require_my_profile(
    db: Session = Depends(get_db),
    staff_user: User = Depends(get_staff_user),
) -> StaffProfile:
    profile = get_staff_profile_for_user(db, staff_user)
    if not profile:
        raise HTTPException(status_code=404, detail="No staff profile is linked to your account")
    return profile


@router.get("", response_model=StaffProfileOut)
def get_my_staff_profile(profile: StaffProfile = Depends(require_my_profile)):
    return profile


# ── My weekly schedule ───────────────────────────────────────────────────────

@router.get("/availability/rules", response_model=List[StaffAvailabilityRuleOut])
def list_my_rules(
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    return availability.list_rules(db, profile.id)


@router.post("/availability/rules", response_model=StaffAvailabilityRuleOut, status_code=201)
def create_my_rule(
    payload: StaffAvailabilityRuleCreate,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    return availability.create_rule(db, profile.id, payload)


@router.delete("/availability/rules/{rule_id}", status_code=204)
def delete_my_rule(
    rule_id: UUID,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    try:
        availability.delete_rule(db, profile.id, rule_id)
    except availability.StaffAvailabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── My one-off exceptions ────────────────────────────────────────────────────

@router.get("/availability/exceptions", response_model=List[StaffAvailabilityExceptionOut])
def list_my_exceptions(
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    return availability.list_exceptions(db, profile.id)


@router.post("/availability/exceptions", response_model=StaffAvailabilityExceptionOut, status_code=201)
def create_my_exception(
    payload: StaffAvailabilityExceptionCreate,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    return availability.create_exception(db, profile.id, payload)


@router.delete("/availability/exceptions/{exception_id}", status_code=204)
def delete_my_exception(
    exception_id: UUID,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    try:
        availability.delete_exception(db, profile.id, exception_id)
    except availability.StaffAvailabilityError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── My booking requests ──────────────────────────────────────────────────────

@router.get("/booking-requests", response_model=List[StaffBookingOut])
def list_my_booking_requests(
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    return list_staff_bookings_for_profile(db, profile.id)


def _my_booking_or_404(db: Session, profile: StaffProfile, staff_booking_id: UUID) -> StaffBooking:
    booking = (
        db.query(StaffBooking)
        .filter(StaffBooking.id == staff_booking_id, StaffBooking.staff_profile_id == profile.id)
        .first()
    )
    if not booking:
        raise HTTPException(status_code=404, detail="Booking request not found")
    return booking


@router.post("/booking-requests/{staff_booking_id}/accept", response_model=StaffBookingOut)
def accept_my_booking_request(
    staff_booking_id: UUID,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    booking = _my_booking_or_404(db, profile, staff_booking_id)
    try:
        return accept_staff_booking(db, booking, actor_id=profile.user_id)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StaffBookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/booking-requests/{staff_booking_id}/decline", response_model=StaffBookingOut)
def decline_my_booking_request(
    staff_booking_id: UUID,
    payload: StaffBookingCancel,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    booking = _my_booking_or_404(db, profile, staff_booking_id)
    try:
        return decline_staff_booking(db, booking, reason=payload.reason, actor_id=profile.user_id)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
