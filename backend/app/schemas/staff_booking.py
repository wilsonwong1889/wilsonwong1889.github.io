from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.booking import validate_booking_duration_minutes
from app.schemas.staff import StaffProfileOut


class StaffBookingCreate(BaseModel):
    staff_profile_id: UUID
    service_type: Optional[str] = Field(default=None, max_length=80)
    start_time: datetime
    duration_minutes: int
    promo_code: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=500, alias="notes")

    @field_validator("start_time")
    @classmethod
    def validate_slot_alignment(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Bookings must include a timezone offset")
        if value.minute != 0 or value.second != 0:
            raise ValueError("Bookings must start on the hour")
        return value.replace(microsecond=0)

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, value: int) -> int:
        return validate_booking_duration_minutes(value, label="Staff bookings")

    model_config = {"populate_by_name": True}


class GuestStaffBookingCreate(StaffBookingCreate):
    guest_name: str = Field(min_length=1, max_length=120)
    guest_phone: str = Field(min_length=7, max_length=40)
    guest_email: Optional[str] = Field(default=None, max_length=255)


class StaffBookingOut(BaseModel):
    id: UUID
    staff_profile_id: UUID
    user_id: Optional[UUID]
    service_type: Optional[str] = None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    original_price_cents: Optional[int] = None
    discount_cents: int = 0
    promo_code: Optional[str] = None
    price_cents: int
    currency: str
    status: str
    booking_code: str
    payment_intent_id: Optional[str] = None
    payment_client_secret: Optional[str] = None
    payment_expires_at: Optional[datetime] = None
    payment_seconds_remaining: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    responded_at: Optional[datetime] = None
    request_expires_at: Optional[datetime] = None
    note: Optional[str] = None
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    user_phone: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    staff_profile: Optional[StaffProfileOut] = None

    model_config = {"from_attributes": True}


class StaffBookingAvailabilityOut(BaseModel):
    staff_profile_id: UUID
    date: date
    timezone: str
    available_start_times: List[str]
    max_duration_minutes_by_start: Dict[str, int]


class StaffBookingCancel(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=200)


class StaffBookingRescheduleIn(BaseModel):
    start_time: datetime

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Bookings must include a timezone offset")
        if value.minute != 0 or value.second != 0:
            raise ValueError("Bookings must start on the hour")
        return value.replace(microsecond=0)


class GuestStaffBookingCreateOut(BaseModel):
    access_token: str
    booking: StaffBookingOut


class StaffBookingFeedItemOut(BaseModel):
    id: UUID
    booking_kind: str = "staff"
    title: str
    subtitle: Optional[str] = None
    status: str
    start_time: datetime
    duration_minutes: int
    price_cents: int
    currency: str
    badge: Optional[str] = None
    image_url: Optional[str] = None
    can_cancel: bool = False
    can_pay: bool = False
