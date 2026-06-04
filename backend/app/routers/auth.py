from __future__ import annotations

from secrets import token_urlsafe

import httpx

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.dependencies import get_current_user
from app.core.rate_limit import rate_limit_dependency
from app.core.security import create_access_token, decode_token, hash_password, verify_password
from app.database import get_db
from app.models.user import User
from app.schemas.user import (
    GoogleAuthExchangeIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    Token,
    UserCreate,
    UserOut,
)
from app.services.booking_service import create_notification_log


router = APIRouter(prefix="/api/auth", tags=["Auth"])
auth_rate_limit = rate_limit_dependency("auth", settings.AUTH_RATE_LIMIT_MAX_REQUESTS)
email_adapter = TypeAdapter(EmailStr)
DUMMY_PASSWORD_HASH = hash_password(token_urlsafe(32))
INVALID_CREDENTIALS_DETAIL = "Invalid email or password."


def _validate_email_address(email: str) -> str:
    try:
        normalized = email_adapter.validate_python((email or "").strip())
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Enter a valid email address.") from exc
    return str(normalized)


def _clear_legacy_login_challenge_state(user: User) -> bool:
    changed = False
    if user.two_factor_enabled:
        user.two_factor_enabled = False
        changed = True
    if user.two_factor_method != "email":
        user.two_factor_method = "email"
        changed = True
    if user.two_factor_code_hash:
        user.two_factor_code_hash = None
        changed = True
    if user.two_factor_code_expires_at:
        user.two_factor_code_expires_at = None
        changed = True
    return changed


def _verify_password_reset_token(db: Session, reset_token: str) -> User:
    try:
        token_payload = decode_token(reset_token)
    except Exception as exc:  # pragma: no cover - jose raises multiple subclasses
        raise HTTPException(status_code=401, detail="Password reset link expired. Request a new one.") from exc

    if token_payload.get("purpose") != "password_reset":
        raise HTTPException(status_code=401, detail="Invalid password reset link")

    user = db.query(User).filter(User.id == token_payload.get("sub")).first()
    if not user:
        raise HTTPException(status_code=404, detail="We couldn't find an account for that reset link.")
    return user


@router.post("/signup", response_model=UserOut, status_code=201)
def signup(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        full_name=payload.full_name,
        phone=payload.phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    notification_details = {
        "queued_tasks": [
            "send_account_created_email",
            "send_account_created_sms",
        ],
    }
    create_notification_log(
        db,
        user_id=user.id,
        booking_id=None,
        notification_type="account_created",
        status="Queued",
        details=notification_details,
    )
    db.commit()
    from app.tasks import (
        send_account_created_email_task,
        send_account_created_sms_task,
        sync_suitedash_contact_task,
    )

    send_account_created_email_task.delay(str(user.id))
    send_account_created_sms_task.delay(str(user.id))
    sync_suitedash_contact_task.delay(str(user.id), "signup")
    return user


@router.post("/google/exchange", response_model=Token)
def google_exchange(
    payload: GoogleAuthExchangeIn,
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
):
    if not settings.SUPABASE_URL or not settings.SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured yet.")

    try:
        response = httpx.get(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {payload.access_token}",
                "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
            },
            timeout=settings.SUPABASE_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Google sign-in could not be verified right now.") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=401, detail="Google sign-in session is invalid or expired.")

    data = response.json()
    email = _validate_email_address(data.get("email", ""))
    metadata = data.get("user_metadata") or {}
    full_name = metadata.get("full_name") or metadata.get("name") or email.split("@", 1)[0]
    phone = metadata.get("phone") or data.get("phone")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(
            email=email,
            password_hash=hash_password(token_urlsafe(32)),
            full_name=full_name,
            phone=phone,
        )
        db.add(user)
        db.flush()
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="account_created",
            status="Sent",
            details={"source": "google_oauth"},
        )
    else:
        if full_name and not user.full_name:
            user.full_name = full_name
        if phone and not user.phone:
            user.phone = phone

    _clear_legacy_login_challenge_state(user)
    db.commit()
    db.refresh(user)
    return Token(access_token=create_access_token({"sub": str(user.id)}), token_type="bearer")


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
):
    email = _validate_email_address(form_data.username)
    user = db.query(User).filter(User.email == email).first()
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    if not verify_password(form_data.password, password_hash) or not user:
        raise HTTPException(status_code=401, detail=INVALID_CREDENTIALS_DETAIL)

    if _clear_legacy_login_challenge_state(user):
        db.commit()
        db.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    return Token(access_token=token, token_type="bearer")


@router.post("/forgot-password", status_code=202)
def forgot_password(
    payload: PasswordResetRequestIn,
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
):
    user = db.query(User).filter(User.email == payload.email).first()
    if user and user.email:
        reset_token = create_access_token(
            {"sub": str(user.id), "purpose": "password_reset"},
            expires_minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
        )
        create_notification_log(
            db,
            user_id=user.id,
            booking_id=None,
            notification_type="password_reset_requested",
            status="Queued",
            details={
                "queued_tasks": ["send_password_reset_email"],
                "expires_in_minutes": settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
            },
        )
        db.commit()

        from app.tasks import send_password_reset_email_task

        send_password_reset_email_task.delay(str(user.id), reset_token)

    return {
        "message": (
            "If we found an account with that email, we sent a password reset link."
        )
    }


@router.post("/reset-password", status_code=204)
def reset_password(
    payload: PasswordResetConfirmIn,
    db: Session = Depends(get_db),
    _: None = Depends(auth_rate_limit),
):
    user = _verify_password_reset_token(db, payload.reset_token)
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Choose a new password that is different from the current one.")

    user.password_hash = hash_password(payload.new_password)
    _clear_legacy_login_challenge_state(user)
    db.commit()


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user
