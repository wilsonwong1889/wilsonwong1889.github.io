from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_admin_manager_user, get_admin_user
from app.core.rate_limit import rate_limit_dependency
from app.database import get_db
from app.models.room import Room
from app.models.staff_profile import StaffProfile  # noqa: F401
from app.models.user import User
from app.schemas.room import RoomOut, RoomPhotoUploadOut, RoomUpdate
from app.schemas.booking import (
    AdminActivityItemOut,
    AdminAnalyticsSummaryOut,
    AdminBookingLookupOut,
    AdminBookingBulkClearResultOut,
    AdminBookingClearByDateIn,
    AdminTodayRosterOut,
    BookingOut,
    ManualBookingCreate,
    RefundCreate,
    RefundOut,
)
from app.schemas.admin import AdminTestCaseOut
from app.schemas.admin import AdminSuiteDashMetaOut, AdminSuiteDashStatusOut
from app.schemas.promo_code import (
    MonthlyMemberCodeRequest,
    MonthlyMemberCodeResult,
    PromoCodeCreate,
    PromoCodeOut,
    PromoCodeUpdate,
)
from app.schemas.staff import AdminStaffProfileOut, StaffPhotoUploadOut, StaffProfileCreate, StaffProfileUpdate
from app.schemas.staff_booking import StaffBookingOut
from app.schemas.user import AdminUserAccountOut, AdminUserDeleteConfirm, AdminUserRoleUpdate
from app.core.image_utils import ACCEPTED_PHOTO_EXTENSIONS, MAX_PHOTO_BYTES, to_jpeg_bytes
from app.core.security import verify_password
from app.services.account_service import (
    apply_user_role,
    can_delete_admin_account,
    count_admin_managers,
    delete_user_account,
    list_accounts_for_admin,
    serialize_admin_account,
)
from app.services.booking_service import (
    check_in_booking,
    create_manual_booking,
    create_audit_log,
    DailyBookingLimitError,
    get_admin_analytics_summary,
    get_admin_today_roster,
    list_recent_admin_activity,
    lookup_bookings_for_admin,
    mark_booking_paid_manually,
    process_refund,
    StaffAvailabilityError,
    StaffSelectionError,
    waive_booking_payment,
    clear_bookings_for_admin_day,
    clear_past_bookings_for_admin,
)
from app.services.payment_service import PaymentBackendError
from app.services.promo_code_service import (
    PromoCodeError,
    create_promo_code,
    generate_monthly_member_codes,
    list_promo_codes,
    update_promo_code,
)
from app.services.staff_service import (
    StaffPhotoError,
    create_staff_profile,
    delete_staff_profile,
    list_staff_profiles,
    save_staff_photo,
    update_staff_profile,
)
from app.services.staff_booking_service import (
    get_staff_booking_for_user,
    list_staff_bookings_for_admin,
    mark_staff_booking_paid_manually,
    waive_staff_booking_payment,
)
from app.services.test_case_service import list_admin_test_cases
from app.services.suitedash_service import (
    SuiteDashConfigurationError,
    SuiteDashRequestError,
    fetch_suitedash_contact_meta,
    get_suitedash_status,
)


router = APIRouter(prefix="/api/admin", tags=["Admin"])
admin_rate_limit = rate_limit_dependency("admin", settings.ADMIN_RATE_LIMIT_MAX_REQUESTS)
ROOM_MEDIA_DIR = Path(__file__).resolve().parents[1] / "frontend" / "media" / "rooms"


@router.get("/analytics/summary", response_model=AdminAnalyticsSummaryOut)
def admin_analytics_summary(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return get_admin_analytics_summary(db)


@router.get("/users", response_model=List[AdminUserAccountOut])
def admin_list_users(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_accounts_for_admin(db)


@router.get("/test-cases", response_model=List[AdminTestCaseOut])
def admin_list_test_cases(
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_admin_test_cases()


@router.get("/integrations/suitedash/status", response_model=AdminSuiteDashStatusOut)
def admin_suitedash_status(
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return get_suitedash_status()


@router.get("/integrations/suitedash/contact-meta", response_model=AdminSuiteDashMetaOut)
def admin_suitedash_contact_meta(
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return {"data": fetch_suitedash_contact_meta()}
    except SuiteDashConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SuiteDashRequestError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.delete("/users/{user_id}", status_code=204)
def admin_delete_user(
    user_id: str,
    payload: AdminUserDeleteConfirm,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_manager_user),
    _: None = Depends(admin_rate_limit),
):
    if not verify_password(payload.admin_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Admin password is incorrect")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="Use the account page to delete your own profile")
    if user.is_admin and not can_delete_admin_account(db, user):
        raise HTTPException(status_code=400, detail="At least one admin account must remain")

    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="user_deleted_by_admin",
        details={"deleted_user_id": str(user.id), "deleted_user_email": user.email},
    )
    delete_user_account(db, user)
    db.commit()


@router.put("/users/{user_id}/role", response_model=AdminUserAccountOut)
def admin_update_user_role(
    user_id: str,
    payload: AdminUserRoleUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_manager_user),
    _: None = Depends(admin_rate_limit),
):
    if not verify_password(payload.admin_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Admin Manager password is incorrect")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_role = user.role
    next_role = payload.role
    if user.id == admin.id and previous_role == "AdminManager" and next_role != "AdminManager":
        if count_admin_managers(db, exclude_user_id=user.id) <= 0:
            raise HTTPException(status_code=400, detail="At least one admin manager account must remain")
    if previous_role == "AdminManager" and next_role != "AdminManager":
        if count_admin_managers(db, exclude_user_id=user.id) <= 0:
            raise HTTPException(status_code=400, detail="At least one admin manager account must remain")

    applied_role = apply_user_role(user, next_role)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="user_role_updated_by_admin_manager",
        details={
            "target_user_id": str(user.id),
            "target_user_email": user.email,
            "previous_role": previous_role,
            "new_role": applied_role,
        },
    )
    db.commit()
    db.refresh(user)
    return serialize_admin_account(user)


@router.get("/activity", response_model=List[AdminActivityItemOut])
def admin_recent_activity(
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_recent_admin_activity(db, limit=limit)


@router.get("/staff", response_model=List[AdminStaffProfileOut])
def admin_list_staff_profiles(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_staff_profiles(db)


@router.post("/staff", response_model=AdminStaffProfileOut, status_code=201)
def admin_create_staff_profile(
    payload: StaffProfileCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        profile = create_staff_profile(db, payload)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="staff_profile_created",
            details={"staff_profile_id": str(profile.id), "name": profile.name},
        )
        db.commit()
        return profile
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/staff/{staff_profile_id}", response_model=AdminStaffProfileOut)
def admin_update_staff_profile(
    staff_profile_id: str,
    payload: StaffProfileUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        profile = update_staff_profile(db, staff_profile_id, payload)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="staff_profile_updated",
            details={"staff_profile_id": str(profile.id), "updated_fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        )
        db.commit()
        return profile
    except ValueError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/staff/{staff_profile_id}", status_code=204)
def admin_delete_staff_profile(
    staff_profile_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        delete_staff_profile(db, staff_profile_id)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="staff_profile_deleted",
            details={"staff_profile_id": staff_profile_id},
        )
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/staff/photo", response_model=StaffPhotoUploadOut)
async def admin_upload_staff_photo(
    photo: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        photo_url = save_staff_photo(await photo.read(), photo.filename)
    except StaffPhotoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"photo_url": photo_url}


@router.post("/rooms/photo", response_model=RoomPhotoUploadOut)
async def admin_upload_room_photo(
    photo: UploadFile = File(...),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    filename = (photo.filename or "").lower()
    if not any(filename.endswith(ext) for ext in ACCEPTED_PHOTO_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG, or WebP photo.")

    file_bytes = await photo.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded photo is empty.")
    if len(file_bytes) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Photo must be 20 MB or smaller.")

    jpeg_bytes = to_jpeg_bytes(file_bytes)
    ROOM_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    saved_filename = f"{uuid4().hex}.jpg"
    saved_path = ROOM_MEDIA_DIR / saved_filename
    saved_path.write_bytes(jpeg_bytes)
    return {"photo_url": f"/assets/media/rooms/{saved_filename}"}


@router.get("/bookings", response_model=List[AdminBookingLookupOut])
def admin_bookings(
    status: Optional[str] = Query(default=None),
    email: Optional[str] = Query(default=None),
    booking_code: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    room_bookings = lookup_bookings_for_admin(
        db,
        status=status,
        email=email,
        booking_code=booking_code,
    )
    staff_bookings = list_staff_bookings_for_admin(
        db,
        status=status,
        email=email,
        booking_code=booking_code,
    )
    return sorted(
        [*room_bookings, *staff_bookings],
        key=lambda item: item["start_time"],
        reverse=True,
    )


@router.get("/today", response_model=AdminTodayRosterOut)
def admin_today_roster(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    """Live-ops view: today's bookings (room+staff merged, chronological)
    with pre-computed counters and a small tomorrow / 7-day outlook."""
    return get_admin_today_roster(db)


@router.get("/promo-codes", response_model=List[PromoCodeOut])
def admin_list_promo_codes(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return list_promo_codes(db)


@router.post("/promo-codes", response_model=PromoCodeOut, status_code=201)
def admin_create_promo_code(
    payload: PromoCodeCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        promo_code = create_promo_code(db, payload)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="promo_code_created",
            details={"code": promo_code["code"]},
        )
        db.commit()
        return promo_code
    except PromoCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/promo-codes/{promo_code_id}", response_model=PromoCodeOut)
def admin_update_promo_code(
    promo_code_id: str,
    payload: PromoCodeUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        promo_code = update_promo_code(db, promo_code_id, payload)
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="promo_code_updated",
            details={"promo_code_id": promo_code_id, "updated_fields": sorted(payload.model_dump(exclude_unset=True).keys())},
        )
        db.commit()
        return promo_code
    except PromoCodeError as exc:
        status_code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/promo-codes/generate-monthly", response_model=MonthlyMemberCodeResult, status_code=201)
def admin_generate_monthly_member_codes(
    payload: MonthlyMemberCodeRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        result = generate_monthly_member_codes(
            db,
            month=payload.month,
            member_category=payload.member_category,
            percent_off=payload.percent_off,
        )
        create_audit_log(
            db,
            actor_id=admin.id,
            booking_id=None,
            action="promo_codes_generated_monthly",
            details={
                "month": result["month"],
                "member_category": result["member_category"],
                "created": result["created"],
                "skipped": result["skipped"],
            },
        )
        db.commit()
        return result
    except PromoCodeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/clear-day", response_model=AdminBookingBulkClearResultOut)
def admin_clear_bookings_for_day(
    payload: AdminBookingClearByDateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return clear_bookings_for_admin_day(db, admin, payload.date)


@router.post("/bookings/clear-past", response_model=AdminBookingBulkClearResultOut)
def admin_clear_past_bookings(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return clear_past_bookings_for_admin(db, admin)


@router.post("/bookings/manual", response_model=AdminBookingLookupOut, status_code=201)
def admin_manual_booking(
    payload: ManualBookingCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        booking = create_manual_booking(db, admin, payload)
    except DailyBookingLimitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffSelectionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StaffAvailabilityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return booking


@router.post("/bookings/{booking_id}/refund", response_model=RefundOut)
def admin_refund_booking(
    booking_id: str,
    payload: RefundCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return process_refund(db, booking_id, admin, payload)
    except PaymentBackendError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/check-in", response_model=BookingOut)
def admin_check_in_booking(
    booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return check_in_booking(db, booking_id, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/waive-payment", response_model=BookingOut)
def admin_waive_booking_payment(
    booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return waive_booking_payment(db, booking_id, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/bookings/{booking_id}/mark-paid", response_model=BookingOut)
def admin_mark_booking_paid(
    booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    try:
        return mark_booking_paid_manually(db, booking_id, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/staff-bookings/{staff_booking_id}/waive-payment", response_model=StaffBookingOut)
def admin_waive_staff_booking_payment(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    booking = get_staff_booking_for_user(db, staff_booking_id, admin)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return waive_staff_booking_payment(db, booking, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/staff-bookings/{staff_booking_id}/mark-paid", response_model=StaffBookingOut)
def admin_mark_staff_booking_paid(
    staff_booking_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    booking = get_staff_booking_for_user(db, staff_booking_id, admin)
    if not booking:
        raise HTTPException(status_code=404, detail="Staff booking not found")
    try:
        return mark_staff_booking_paid_manually(db, booking, admin)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rooms", response_model=List[RoomOut])
def admin_list_rooms(
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    return db.query(Room).order_by(Room.created_at.desc()).all()


@router.get("/rooms/{room_id}", response_model=RoomOut)
def admin_get_room(
    room_id: str,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room


@router.put("/rooms/{room_id}", response_model=RoomOut)
def admin_update_room(
    room_id: str,
    payload: RoomUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_admin_user),
    _: None = Depends(admin_rate_limit),
):
    room = db.query(Room).filter(Room.id == room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(room, field, value)
    create_audit_log(
        db,
        actor_id=admin.id,
        booking_id=None,
        action="room_updated",
        details={"room_id": room_id, "updated_fields": sorted(update_data.keys())},
    )
    db.commit()
    db.refresh(room)
    return room
