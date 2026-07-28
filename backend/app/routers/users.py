from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy.orm import Session
from app.core.image_utils import to_jpeg_bytes as _to_jpeg_bytes
from app.core.media_storage import store_media
from app.database import get_db
from app.models.user import User
from app.roles import user_has_admin_access
from app.schemas.user import UserDeleteConfirm, UserOut, UserPasswordUpdate, UserUpdate
from app.core.dependencies import get_current_user
from app.core.security import hash_password, verify_password
from app.services.account_service import can_delete_admin_account, delete_user_account
from app.services.booking_service import create_audit_log

router = APIRouter(prefix="/api/users", tags=["Users"])


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
    jpeg_bytes = _to_jpeg_bytes(await photo.read())
    avatar_url = store_media(jpeg_bytes, folder="avatars")
    return {"avatar_url": avatar_url}


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
