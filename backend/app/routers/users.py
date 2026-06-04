from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session
from app.core.image_utils import ACCEPTED_PHOTO_EXTENSIONS as ACCEPTED_AVATAR_EXTENSIONS
from app.core.image_utils import MAX_PHOTO_BYTES as MAX_AVATAR_BYTES
from app.core.image_utils import to_jpeg_bytes as _to_jpeg_bytes
from app.database import get_db
from app.models.user import User
from app.roles import user_has_admin_access
from app.schemas.user import UserDeleteConfirm, UserOut, UserPasswordUpdate, UserUpdate
from app.core.dependencies import get_current_user
from app.core.security import hash_password, verify_password
from app.services.account_service import can_delete_admin_account, delete_user_account
from app.services.booking_service import create_audit_log

router = APIRouter(prefix="/api/users", tags=["Users"])
AVATAR_MEDIA_DIR = Path(__file__).resolve().parents[1] / "frontend" / "media" / "avatars"


@router.get("/me", response_model=UserOut)
def get_profile(current_user: User = Depends(get_current_user)):
    return current_user

@router.put("/me", response_model=UserOut)
def update_profile(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    from app.tasks import sync_suitedash_contact_task

    sync_suitedash_contact_task.delay(str(current_user.id), "profile_update")
    return current_user


@router.post("/me/avatar", response_model=dict)
async def upload_profile_avatar(
    photo: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    filename = (photo.filename or "").lower()
    if not any(filename.endswith(ext) for ext in ACCEPTED_AVATAR_EXTENSIONS):
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG, or WebP photo.")

    file_bytes = await photo.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded avatar is empty.")
    if len(file_bytes) > MAX_AVATAR_BYTES:
        raise HTTPException(status_code=400, detail="Avatar image must be 20 MB or smaller.")

    jpeg_bytes = _to_jpeg_bytes(file_bytes)
    AVATAR_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    saved_filename = f"{uuid4().hex}.jpg"
    saved_path = AVATAR_MEDIA_DIR / saved_filename
    saved_path.write_bytes(jpeg_bytes)
    return {"avatar_url": f"/assets/media/avatars/{saved_filename}"}


@router.put("/me/password", status_code=204)
def update_password(
    payload: UserPasswordUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if not verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=400, detail="New password must be different")

    current_user.password_hash = hash_password(payload.new_password)
    db.commit()


@router.delete("/me", status_code=204)
def delete_profile(
    payload: UserDeleteConfirm,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Password is incorrect")
    if user_has_admin_access(current_user) and not can_delete_admin_account(db, current_user):
        raise HTTPException(status_code=400, detail="At least one admin account must remain")

    create_audit_log(
        db,
        actor_id=current_user.id,
        booking_id=None,
        action="user_self_deleted",
        details={"deleted_user_id": str(current_user.id), "deleted_user_email": current_user.email},
    )
    delete_user_account(db, current_user)
    db.commit()
    return Response(status_code=204)
