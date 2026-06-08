from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_user, get_current_user
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.staff_booking import StaffBooking
from app.models.user import User
from app.schemas.booking import BookingContactUpdate, PaymentSessionOut
from app.schemas.staff_booking import (
    GuestStaffBookingCreate,
    GuestStaffBookingCreateOut,
    StaffBookingAvailabilityOut,
    StaffBookingCancel,
    StaffBookingCreate,
    StaffBookingOut,
    StaffBookingRescheduleIn,
)
from app.services.booking_service import DailyBookingLimitError, PaymentSessionError
from app.services.payment_service import PaymentBackendError
from app.services.staff_token_service import (
    StaffTokenError,
    mark_token_used,
    resolve_response_token,
)
from app.services.staff_booking_service import (
    StaffBookingConflictError,
    StaffBookingStateError,
    accept_staff_booking,
    cancel_staff_booking,
    confirm_free_staff_booking,
    confirm_staff_booking_request,
    create_guest_staff_booking,
    create_staff_booking,
    decline_staff_booking,
    get_staff_availability,
    get_staff_booking_for_user,
    get_staff_booking_payment_session,
    get_staff_monthly_availability_summary,
    list_staff_bookings_for_user,
    reschedule_staff_booking,
    update_staff_booking_contact,
)


router = APIRouter(prefix="/api", tags=["Staff Bookings"])
booking_rate_limit = rate_limit_dependency("booking", settings.BOOKING_RATE_LIMIT_MAX_REQUESTS)


@router.get("/staff/{staff_profile_id}/availability", response_model=StaffBookingAvailabilityOut)
def staff_availability(
    staff_profile_id: str,
    date_value: date = Query(alias="date"),
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    try:
        return get_staff_availability(db, staff_profile_id, date_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/staff/{staff_profile_id}/availability/monthly")
def staff_monthly_availability(
    staff_profile_id: str,
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    try:
        return get_staff_monthly_availability_summary(db, staff_profile_id, month)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/staff-bookings", response_model=StaffBookingOut, status_code=201)
def create_staff_booking_endpoint(
    payload: StaffBookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_staff_booking(db, current_user, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffBookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/staff-bookings/guest", response_model=GuestStaffBookingCreateOut, status_code=201)
def create_guest_staff_booking_endpoint(
    payload: GuestStaffBookingCreate,
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_guest_staff_booking(db, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffBookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/staff-bookings", response_model=List[StaffBookingOut])
def list_my_staff_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_staff_bookings_for_user(db, current_user)


@router.get("/staff-bookings/{staff_booking_id}", response_model=StaffBookingOut)
def get_my_staff_booking(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = get_staff_booking_for_user(db, staff_booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    return booking


@router.post("/staff-bookings/{staff_booking_id}/payment-session", response_model=PaymentSessionOut)
def get_my_staff_booking_payment_session(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_staff_booking_for_user(db, staff_booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return get_staff_booking_payment_session(db, booking, current_user)
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/staff-bookings/{staff_booking_id}/contact", response_model=StaffBookingOut)
def update_my_staff_booking_contact(
    staff_booking_id: str,
    payload: BookingContactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_staff_booking_for_user(db, staff_booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    return update_staff_booking_contact(db, booking, current_user, payload)


@router.post("/staff-bookings/{staff_booking_id}/confirm", response_model=StaffBookingOut)
def confirm_my_free_staff_booking(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    """Customer completes the free $0 confirmation for an accepted staff booking."""
    booking = get_staff_booking_for_user(db, staff_booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return confirm_free_staff_booking(db, booking)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/staff-bookings/{staff_booking_id}/confirm-request", response_model=StaffBookingOut)
def confirm_my_staff_booking_request(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    """Double-confirmation: the customer sends their held request to the staff member."""
    booking = get_staff_booking_for_user(db, staff_booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return confirm_staff_booking_request(db, booking)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/staff-bookings/{staff_booking_id}/cancel", response_model=StaffBookingOut)
def cancel_my_staff_booking(
    staff_booking_id: str,
    payload: StaffBookingCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_staff_booking_for_user(db, staff_booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return cancel_staff_booking(db, booking, current_user, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _respond_to_request_via_token(db, staff_booking_id, token, *, action, reason=None):
    booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        token_row = resolve_response_token(db, booking.id, token)
    except StaffTokenError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    try:
        if action == "accept":
            result = accept_staff_booking(db, booking, actor_id=None)
        else:
            result = decline_staff_booking(db, booking, reason=reason, actor_id=None)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StaffBookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    mark_token_used(token_row)
    db.commit()
    return result


@router.post("/staff-bookings/{staff_booking_id}/accept", response_model=StaffBookingOut)
def respond_accept_staff_booking(
    staff_booking_id: str,
    token: str = Query(...),
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    """Public, token-authenticated accept link for the staff member (no login)."""
    return _respond_to_request_via_token(db, staff_booking_id, token, action="accept")


@router.post("/staff-bookings/{staff_booking_id}/decline", response_model=StaffBookingOut)
def respond_decline_staff_booking(
    staff_booking_id: str,
    token: str = Query(...),
    reason: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    """Public, token-authenticated decline link for the staff member (no login)."""
    return _respond_to_request_via_token(db, staff_booking_id, token, action="decline", reason=reason)


@router.post("/admin/staff-bookings/{staff_booking_id}/accept", response_model=StaffBookingOut)
def admin_accept_staff_booking(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(booking_rate_limit),
):
    booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return accept_staff_booking(db, booking, actor_id=admin.id)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except StaffBookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/admin/staff-bookings/{staff_booking_id}/decline", response_model=StaffBookingOut)
def admin_decline_staff_booking(
    staff_booking_id: str,
    payload: StaffBookingCancel,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(booking_rate_limit),
):
    booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return decline_staff_booking(db, booking, reason=payload.reason, actor_id=admin.id)
    except StaffBookingStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/staff-bookings/{staff_booking_id}/reschedule", response_model=StaffBookingOut)
def reschedule_staff_booking_admin_only(
    staff_booking_id: str,
    payload: StaffBookingRescheduleIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(booking_rate_limit),
):
    booking = db.query(StaffBooking).filter(StaffBooking.id == staff_booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return reschedule_staff_booking(db, booking, admin, payload)
    except StaffBookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
