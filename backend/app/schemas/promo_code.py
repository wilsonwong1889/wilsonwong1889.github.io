from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


def normalize_promo_code(code: str) -> str:
    normalized = str(code or "").strip().upper().replace(" ", "")
    if not normalized:
        raise ValueError("Promo code is required")
    return normalized


class PromoCodeBase(BaseModel):
    code: str
    description: Optional[str] = None
    percent_off: Optional[int] = Field(default=None, ge=1, le=100)
    amount_off_cents: Optional[int] = Field(default=None, ge=1)
    active: bool = True
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    member_category: Optional[str] = Field(default=None, max_length=60)
    member_unique: bool = False
    valid_month: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return normalize_promo_code(value)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if isinstance(value, str) else value

    @field_validator("expires_at")
    @classmethod
    def validate_expiry(cls, value: Optional[datetime], info):
        starts_at = info.data.get("starts_at")
        if value and starts_at and value <= starts_at:
            raise ValueError("Promo code expiry must be after the start time")
        return value


class PromoCodeCreate(PromoCodeBase):
    pass


class PromoCodeUpdate(BaseModel):
    code: Optional[str] = None
    description: Optional[str] = None
    percent_off: Optional[int] = Field(default=None, ge=1, le=100)
    amount_off_cents: Optional[int] = Field(default=None, ge=1)
    active: Optional[bool] = None
    max_redemptions: Optional[int] = Field(default=None, ge=1)
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    member_category: Optional[str] = Field(default=None, max_length=60)
    member_unique: Optional[bool] = None
    valid_month: Optional[str] = Field(default=None, pattern=r"^\d{4}-\d{2}$")

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        return normalize_promo_code(value)

    @field_validator("description")
    @classmethod
    def clean_description(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() or None if isinstance(value, str) else value


class PromoCodeOut(BaseModel):
    id: UUID
    code: str
    description: Optional[str] = None
    percent_off: Optional[int] = None
    amount_off_cents: Optional[int] = None
    active: bool
    max_redemptions: Optional[int] = None
    starts_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    member_category: Optional[str] = None
    member_unique: bool = False
    assigned_user_id: Optional[UUID] = None
    valid_month: Optional[str] = None
    active_redemptions: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class PromoCodePreviewIn(BaseModel):
    code: str
    amount_cents: int = Field(ge=0)

    @field_validator("code")
    @classmethod
    def validate_code(cls, value: str) -> str:
        return normalize_promo_code(value)


class PromoCodePreviewOut(BaseModel):
    code: str
    description: Optional[str] = None
    amount_cents: int
    discount_cents: int
    final_amount_cents: int
    percent_off: Optional[int] = None
    amount_off_cents: Optional[int] = None


class MonthlyMemberCodeRequest(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    member_category: str = Field(min_length=1, max_length=60)
    percent_off: int = Field(default=50, ge=1, le=100)


class MonthlyMemberCodeResult(BaseModel):
    month: str
    member_category: str
    percent_off: int
    created: int
    skipped: int
    codes: List[PromoCodeOut] = Field(default_factory=list)
