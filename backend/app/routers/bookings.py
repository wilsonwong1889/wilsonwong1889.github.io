from datetime import date
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user, get_optional_current_user
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.user import User
from app.schemas.booking import (
    BookingAvailabilityOut,
    BookingCancel,
    BookingContactUpdate,
    BookingCreate,
    BookingRescheduleIn,
    GuestBookingCreate,
    GuestBookingCreateOut,
    BookingOut,
    PaymentSessionOut,
    ReservationCreate,
    ReservationOut,
)
from app.schemas.promo_code import PromoCodePreviewIn, PromoCodePreviewOut
from app.schemas.review import ReviewCreate, ReviewOut
from app.services.booking_service import (
    BookingConflictError,
    DailyBookingLimitError,
    cancel_booking,
    create_or_update_booking_review,
    create_booking,
    create_guest_booking,
    create_reservation_hold,
    get_booking_payment_session,
    get_booking_for_user,
    get_booking_review_for_user,
    get_monthly_availability_summary,
    get_room_availability,
    list_booking_feed_for_user,
    list_bookings_for_user,
    PaymentSessionError,
    PastBookingError,
    reschedule_booking,
    StaffAvailabilityError,
    StaffSelectionError,
    update_booking_contact,
)
from app.config import settings
from app.services.payment_service import PaymentBackendError
from app.services.promo_code_service import PromoCodeError, calculate_discount_for_amount
from app.services.receipt_service import (
    booking_receipt_available,
    build_booking_receipt_filename,
    build_booking_receipt_pdf,
)
from app.services.staff_booking_service import build_staff_booking_feed_item, list_staff_bookings_for_user


router = APIRouter(prefix="/api", tags=["Bookings"])
booking_rate_limit = rate_limit_dependency("booking", settings.BOOKING_RATE_LIMIT_MAX_REQUESTS)


@router.get("/rooms/{room_id}/availability", response_model=BookingAvailabilityOut)
def room_availability(
    room_id: str,
    date_value: date = Query(alias="date"),
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    try:
        return get_room_availability(db, room_id, date_value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/availability/monthly")
def monthly_availability(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    return get_monthly_availability_summary(db, month)


@router.post("/bookings/reservations", response_model=ReservationOut, status_code=201)
def create_reservation(
    payload: ReservationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_reservation_hold(
            db,
            payload.room_id,
            payload.start_time,
            payload.duration_minutes,
        )
    except PastBookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/bookings/reservations", status_code=204)
def release_reservation(
    token: str,
    slot_keys: List[str] = Query(default_factory=list),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    if not slot_keys:
        return
    from app.services.reservation_service import release_hold

    release_hold(slot_keys, token)


@router.post("/bookings", response_model=BookingOut, status_code=201)
def create_booking_endpoint(
    payload: BookingCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_booking(db, current_user, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffAvailabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PromoCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PastBookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/bookings/guest", response_model=GuestBookingCreateOut, status_code=201)
def create_guest_booking_endpoint(
    payload: GuestBookingCreate,
    db: Session = Depends(get_db),
    _: None = Depends(booking_rate_limit),
):
    try:
        return create_guest_booking(db, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffAvailabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PromoCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PastBookingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/bookings", response_model=List[BookingOut])
def list_my_bookings(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return list_bookings_for_user(db, current_user)


@router.get("/bookings/feed", response_model=List[dict])
def list_my_bookings_feed(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    room_bookings = list_booking_feed_for_user(db, current_user)
    staff_bookings = [build_staff_booking_feed_item(booking) for booking in list_staff_bookings_for_user(db, current_user)]
    return sorted(
        [*room_bookings, *staff_bookings],
        key=lambda item: item.get("start_time"),
        reverse=True,
    )


@router.get("/bookings/{booking_id}", response_model=BookingOut)
def get_my_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return booking


@router.post("/public/promo-codes/preview", response_model=PromoCodePreviewOut, include_in_schema=False)
def preview_promo_code(
    payload: PromoCodePreviewIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_optional_current_user),
):
    try:
        result = calculate_discount_for_amount(db, payload.code, payload.amount_cents, current_user)
    except PromoCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    promo_code = result["promo_code"]
    return {
        "code": promo_code.code,
        "description": promo_code.description,
        "amount_cents": payload.amount_cents,
        "discount_cents": result["discount_cents"],
        "final_amount_cents": result["final_amount_cents"],
        "percent_off": promo_code.percent_off,
        "amount_off_cents": promo_code.amount_off_cents,
    }


@router.get("/bookings/{booking_id}/receipt")
def download_my_booking_receipt(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not booking_receipt_available(booking):
        raise HTTPException(status_code=400, detail="Receipt is only available after payment is settled")

    return Response(
        content=build_booking_receipt_pdf(db, booking),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{build_booking_receipt_filename(booking)}"'
        },
    )


@router.post("/bookings/{booking_id}/payment-session", response_model=PaymentSessionOut)
def get_my_booking_payment_session(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        return get_booking_payment_session(db, booking, current_user)
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except PaymentSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/bookings/{booking_id}/contact", response_model=BookingOut)
def update_my_booking_contact(
    booking_id: str,
    payload: BookingContactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    return update_booking_contact(db, booking, current_user, payload)


@router.post("/bookings/{booking_id}/cancel", response_model=BookingOut)
def cancel_my_booking(
    booking_id: str,
    payload: BookingCancel,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        return cancel_booking(db, booking, current_user, payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/reschedule", response_model=BookingOut)
def reschedule_my_booking(
    booking_id: str,
    payload: BookingRescheduleIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        return reschedule_booking(db, booking, current_user, payload)
    except BookingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/bookings/{booking_id}/review", response_model=ReviewOut)
def get_my_booking_review(
    booking_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        review = get_booking_review_for_user(db, booking, current_user)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    return review


@router.put("/bookings/{booking_id}/review", response_model=ReviewOut)
def save_my_booking_review(
    booking_id: str,
    payload: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    _: None = Depends(booking_rate_limit),
):
    booking = get_booking_for_user(db, booking_id, current_user)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    try:
        return create_or_update_booking_review(db, booking, current_user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
