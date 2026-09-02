"""Staff self-service portal: a staff member manages their own schedule and
responds to their own booking requests in-app (no email/SMS required)."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from app.core.image_utils import read_upload_within_limit
from sqlalchemy.orm import Session

from app.core.dependencies import get_staff_user
from app.database import get_db
from app.models.staff_booking import StaffBooking
from app.models.staff_profile import StaffProfile
from app.models.user import User
from app.schemas.staff import StaffPhotoUploadOut, StaffProfileOut, StaffSelfProfileUpdate
from app.schemas.staff_availability import (
    StaffAvailabilityBulkRuleCreate,
    StaffAvailabilityExceptionCreate,
    StaffAvailabilityExceptionOut,
    StaffAvailabilityRuleCreate,
    StaffAvailabilityRuleOut,
    StaffWeekdayWindowsUpdate,
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
from app.services.staff_service import (
    StaffPhotoError,
    get_staff_profile_for_user,
    save_staff_photo,
    update_own_staff_profile,
)

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


@router.put("", response_model=StaffProfileOut)
def update_my_staff_profile(
    payload: StaffSelfProfileUpdate,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    """Staff edit their own profile. Pricing, publish-to-public, account link,
    active/approval status and assignments stay admin-only (not in the schema)."""
    try:
        return update_own_staff_profile(db, profile, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/photo", response_model=StaffPhotoUploadOut)
async def upload_my_staff_photo(
    photo: UploadFile = File(...),
    _: StaffProfile = Depends(require_my_profile),
):
    try:
        photo_url = save_staff_photo(await read_upload_within_limit(photo), photo.filename)
    except StaffPhotoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"photo_url": photo_url}


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


@router.post("/availability/rules/bulk", response_model=List[StaffAvailabilityRuleOut], status_code=201)
def create_my_rules_bulk(
    payload: StaffAvailabilityBulkRuleCreate,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    """Apply one window to several weekdays at once (set a typical week)."""
    return availability.create_rules_bulk(db, profile.id, payload)


@router.put("/availability/rules/weekday/{weekday}", response_model=List[StaffAvailabilityRuleOut])
def set_my_weekday_rules(
    weekday: int,
    payload: StaffWeekdayWindowsUpdate,
    db: Session = Depends(get_db),
    profile: StaffProfile = Depends(require_my_profile),
):
    """Replace all windows for one weekday (the per-day editor)."""
    try:
        return availability.set_weekday_rules(db, profile.id, weekday, payload)
    except availability.StaffAvailabilityError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
