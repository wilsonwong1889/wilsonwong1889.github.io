"""Self-service studio-engineer application: any logged-in user can create and
submit their own staff profile for admin review (no Staff role required yet)."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.dependencies import get_current_user
from app.database import get_db
from app.models.user import User
from app.roles import user_has_staff_access
from app.schemas.staff import (
    StaffApplicationStateOut,
    StaffPhotoUploadOut,
    StaffSelfProfileUpdate,
)
from app.services.staff_service import (
    StaffPhotoError,
    get_staff_profile_for_user,
    save_staff_photo,
    submit_staff_application,
)

router = APIRouter(prefix="/api/staff/application", tags=["Staff Application"])


@router.get("", response_model=StaffApplicationStateOut)
def get_my_application(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return {
        "is_staff": user_has_staff_access(current_user),
        "profile": get_staff_profile_for_user(db, current_user),
    }


@router.put("", response_model=StaffApplicationStateOut)
def submit_my_application(
    payload: StaffSelfProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        profile = submit_staff_application(db, current_user, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"is_staff": user_has_staff_access(current_user), "profile": profile}


@router.post("/photo", response_model=StaffPhotoUploadOut)
async def upload_my_application_photo(
    photo: UploadFile = File(...),
    _: User = Depends(get_current_user),
):
    try:
        photo_url = save_staff_photo(await photo.read(), photo.filename)
    except StaffPhotoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"photo_url": photo_url}
