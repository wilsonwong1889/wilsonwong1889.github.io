from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError
from app.database import get_db
from app.models.user import User
from app.roles import user_has_admin_access, user_has_admin_manager_access, user_has_staff_access
from app.core.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
optional_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> User:
    return _resolve_user_from_token(token=token, db=db)


def get_optional_current_user(
    token: Optional[str] = Depends(optional_oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[User]:
    if not token:
        return None
    return _resolve_user_from_token(token=token, db=db)


def _resolve_user_from_token(token: str, db: Session) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise credentials_exception
    return user


def get_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if not user_has_admin_access(current_user):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def get_admin_manager_user(current_user: User = Depends(get_admin_user)) -> User:
    if not user_has_admin_manager_access(current_user):
        raise HTTPException(status_code=403, detail="Admin Manager access required")
    return current_user


def get_staff_user(current_user: User = Depends(get_current_user)) -> User:
    if not user_has_staff_access(current_user):
        raise HTTPException(status_code=403, detail="Staff access required")
    return current_user
