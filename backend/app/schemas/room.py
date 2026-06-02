from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.booking import (
    BOOKING_DURATION_STEP_MINUTES,
    MAX_BOOKING_DURATION_MINUTES,
    MIN_BOOKING_DURATION_MINUTES,
)
from app.schemas.staff import StaffOption
from app.staffing import normalize_staff_roles


def validate_room_max_duration(value: int) -> int:
    if (
        value < MIN_BOOKING_DURATION_MINUTES
        or value > MAX_BOOKING_DURATION_MINUTES
        or value % BOOKING_DURATION_STEP_MINUTES != 0
    ):
        raise ValueError("Room max booking duration must be between 1 hour and 5 hours in 1-hour increments")
    return value


class RoomCreate(BaseModel):
    name: str
    description: Optional[str] = None
    capacity: Optional[int] = Field(default=None, ge=1)
    photos: List[str] = Field(default_factory=list)
    staff_roles: List[StaffOption] = Field(default_factory=list)
    hourly_rate_cents: int = Field(default=5000, ge=0)
    deposit_cents: int = Field(default=2000, ge=0)
    max_booking_duration_minutes: int = Field(default=300)
    status: str = "available"

    @field_validator("photos")
    @classmethod
    def normalize_photos(cls, value: List[str]) -> List[str]:
        return [photo for photo in value if photo]

    @field_validator("staff_roles", mode="before")
    @classmethod
    def normalize_staff_roles(cls, value):
        return normalize_staff_roles(value)

    @field_validator("max_booking_duration_minutes")
    @classmethod
    def validate_max_booking_duration(cls, value: int) -> int:
        return validate_room_max_duration(value)

ROOM_STATUS_VALUES = ("available", "in_progress", "tbc")


class RoomOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    capacity: Optional[int]
    photos: List[str] = Field(default_factory=list)
    staff_roles: List[StaffOption] = Field(default_factory=list)
    hourly_rate_cents: int
    deposit_cents: int = 2000
    max_booking_duration_minutes: int
    active: bool
    coming_soon: bool = False
    status: str = "available"
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("photos", mode="before")
    @classmethod
    def normalize_output_photos(cls, value):
        return [photo for photo in (value or []) if photo]

    @field_validator("staff_roles", mode="before")
    @classmethod
    def normalize_output_staff_roles(cls, value):
        return normalize_staff_roles(value)

    model_config = {"from_attributes": True}

class RoomUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    capacity: Optional[int] = Field(default=None, ge=1)
    photos: Optional[List[str]] = None
    staff_roles: Optional[List[StaffOption]] = None
    hourly_rate_cents: Optional[int] = Field(default=None, ge=0)
    deposit_cents: Optional[int] = Field(default=None, ge=0)
    max_booking_duration_minutes: Optional[int] = None
    active: Optional[bool] = None
    coming_soon: Optional[bool] = None
    status: Optional[str] = None

    @field_validator("photos")
    @classmethod
    def normalize_photos(cls, value: Optional[List[str]]) -> Optional[List[str]]:
        if value is None:
            return value
        return [photo for photo in value if photo]

    @field_validator("staff_roles", mode="before")
    @classmethod
    def normalize_room_staff_roles(cls, value):
        if value is None:
            return value
        return normalize_staff_roles(value)

    @field_validator("max_booking_duration_minutes")
    @classmethod
    def validate_optional_max_booking_duration(cls, value: Optional[int]) -> Optional[int]:
        if value is None:
            return value
        return validate_room_max_duration(value)


class RoomPhotoUploadOut(BaseModel):
    photo_url: str
