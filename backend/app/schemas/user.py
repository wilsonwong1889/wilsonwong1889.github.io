from pydantic import BaseModel, EmailStr, Field, field_validator
from uuid import UUID
from typing import Optional
from datetime import date, datetime

from app.roles import normalize_user_role


class BillingAddress(BaseModel):
    line1: str
    line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str
    phone: Optional[str] = None

class UserOut(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str] = None
    phone: Optional[str]
    birthday: Optional[date] = None
    billing_address: Optional[BillingAddress] = None
    emergency_contact: Optional[str] = None
    visible_minority: Optional[str] = None
    city: Optional[str] = None
    opt_in_email: bool
    opt_in_sms: bool
    is_admin: bool
    role: str = "Customer"
    user_category: str = "general_public"
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class AdminUserAccountOut(BaseModel):
    id: UUID
    email: str
    full_name: Optional[str]
    avatar_url: Optional[str] = None
    phone: Optional[str]
    birthday: Optional[date] = None
    billing_address: Optional[BillingAddress] = None
    emergency_contact: Optional[str] = None
    visible_minority: Optional[str] = None
    city: Optional[str] = None
    opt_in_email: bool
    opt_in_sms: bool
    is_admin: bool
    role: str = "Customer"
    booking_count: int = 0
    last_booking_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    birthday: Optional[date] = None
    opt_in_email: Optional[bool] = None
    opt_in_sms: Optional[bool] = None
    billing_address: Optional[BillingAddress] = None
    emergency_contact: Optional[str] = None
    visible_minority: Optional[str] = None
    city: Optional[str] = None


class UserPasswordUpdate(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class UserDeleteConfirm(BaseModel):
    password: str = Field(min_length=1, max_length=128)


class AdminUserDeleteConfirm(BaseModel):
    admin_password: str = Field(min_length=1, max_length=128)


class AdminUserRoleUpdate(BaseModel):
    role: str
    admin_password: str = Field(min_length=1, max_length=128)

    @field_validator("role")
    @classmethod
    def validate_role(cls, value):
        normalized_input = str(value or "").strip().replace(" ", "").replace("_", "").lower()
        allowed_inputs = {
            "customer",
            "staff",
            "engineer",
            "serviceengineer",
            "admin",
            "adminmanager",
            "manager",
            "techadmin",
            "superadmin",
        }
        if normalized_input not in allowed_inputs:
            raise ValueError("Unsupported user role")
        normalized = normalize_user_role(value)
        return normalized

class Token(BaseModel):
    access_token: Optional[str] = None
    token_type: str = "bearer"


class GoogleAuthExchangeIn(BaseModel):
    access_token: str = Field(min_length=1)


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetConfirmIn(BaseModel):
    reset_token: str
    new_password: str = Field(min_length=8, max_length=128)
