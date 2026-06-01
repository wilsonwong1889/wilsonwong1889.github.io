from datetime import date, datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.staff import StaffOption
from app.staffing import normalize_staff_roles, normalize_staff_selection_ids

MIN_BOOKING_DURATION_MINUTES = 60
MAX_BOOKING_DURATION_MINUTES = 300
BOOKING_DURATION_STEP_MINUTES = 60


def validate_booking_duration_minutes(value: int, *, label: str) -> int:
    if (
        value < MIN_BOOKING_DURATION_MINUTES
        or value > MAX_BOOKING_DURATION_MINUTES
        or value % BOOKING_DURATION_STEP_MINUTES != 0
    ):
        raise ValueError(f"{label} must be between 1 hour and 5 hours in 1-hour increments")
    return value


class BookingCreate(BaseModel):
    room_id: UUID
    start_time: datetime
    duration_minutes: int
    payment_method_id: Optional[str] = None
    reservation_token: Optional[str] = None
    promo_code: Optional[str] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    staff_assignments: List[str] = Field(default_factory=list)
    with_engineer: bool = False
    user_category: str = "general_public"

    @field_validator("start_time")
    @classmethod
    def validate_slot_alignment(cls, v):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Bookings must include a timezone offset")
        if v.minute != 0 or v.second != 0:
            raise ValueError("Bookings must start on the hour")
        return v.replace(microsecond=0)

    @field_validator("duration_minutes")
    @classmethod
    def validate_duration(cls, v):
        return validate_booking_duration_minutes(v, label="Bookings")

    @field_validator("staff_assignments", mode="before")
    @classmethod
    def normalize_staff_assignments(cls, value):
        return normalize_staff_selection_ids(value)


class GuestBookingCreate(BookingCreate):
    guest_name: str = Field(min_length=1, max_length=120)
    guest_phone: str = Field(min_length=7, max_length=40)

class BookingOut(BaseModel):
    id: UUID
    room_id: UUID
    user_id: Optional[UUID]
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    original_price_cents: Optional[int] = None
    discount_cents: int = 0
    promo_code: Optional[str] = None
    tax_cents: int = 0
    price_cents: int
    currency: str
    status: str
    booking_code: str
    payment_intent_id: Optional[str] = None
    payment_client_secret: Optional[str] = None
    payment_expires_at: Optional[datetime] = None
    payment_seconds_remaining: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    note: Optional[str] = None
    deposit_amount_cents: int = 0
    deposit_paid: bool = False
    deposit_with_engineer: bool = False
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    user_phone: Optional[str] = None
    room_name_snapshot: Optional[str] = None
    room_description_snapshot: Optional[str] = None
    staff_assignments: List[StaffOption] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("staff_assignments", mode="before")
    @classmethod
    def normalize_output_staff_assignments(cls, value):
        return normalize_staff_roles(value)

    model_config = {"from_attributes": True}


class BookingAvailabilityOut(BaseModel):
    room_id: UUID
    date: date
    timezone: str
    available_start_times: List[str]
    max_duration_minutes_by_start: Dict[str, int]


class ReservationCreate(BaseModel):
    room_id: UUID
    start_time: datetime
    duration_minutes: int

    @field_validator("start_time")
    @classmethod
    def validate_reservation_alignment(cls, v):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Reservations must include a timezone offset")
        if v.minute != 0 or v.second != 0:
            raise ValueError("Reservations must start on the hour")
        return v.replace(microsecond=0)

    @field_validator("duration_minutes")
    @classmethod
    def validate_reservation_duration(cls, v):
        return validate_booking_duration_minutes(v, label="Reservations")


class ReservationOut(BaseModel):
    token: str
    expires_at: int
    slot_keys: List[str]


class BookingCancel(BaseModel):
    reason: Optional[str] = None


class BookingContactUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=40)
    note: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("full_name", "email", "phone", "note", mode="before")
    @classmethod
    def normalize_optional_text(cls, value):
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None


class BookingRescheduleIn(BaseModel):
    start_time: datetime

    @field_validator("start_time")
    @classmethod
    def validate_start_time(cls, v):
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Bookings must include a timezone offset")
        if v.minute != 0 or v.second != 0:
            raise ValueError("Bookings must start on the hour")
        return v.replace(microsecond=0)


class PaymentSessionOut(BaseModel):
    booking_id: UUID
    payment_intent_id: str
    payment_client_secret: str
    payment_backend: str
    stripe_publishable_key: Optional[str] = None
    payment_expires_at: Optional[datetime] = None
    payment_seconds_remaining: Optional[int] = None


class GuestBookingCreateOut(BaseModel):
    access_token: str
    booking: BookingOut


class AdminAnalyticsRoomSummaryOut(BaseModel):
    room_id: UUID
    room_name: str
    total_bookings: int
    paid_bookings: int
    revenue_cents: int


class AdminAnalyticsStaffSummaryOut(BaseModel):
    staff_id: str
    staff_name: str
    total_bookings: int
    revenue_cents: int
    assigned_rooms: int
    active: bool


class AdminAnalyticsSummaryOut(BaseModel):
    currency: str
    total_bookings: int
    pending_bookings: int
    paid_bookings: int
    cancelled_bookings: int
    refunded_bookings: int
    gross_revenue_cents: int
    refunded_revenue_cents: int
    net_revenue_cents: int
    active_rooms: int
    total_staff_profiles: int
    active_staff_profiles: int
    staff_assignment_count: int
    room_summaries: List[AdminAnalyticsRoomSummaryOut]
    staff_summaries: List[AdminAnalyticsStaffSummaryOut]


class AdminActivityItemOut(BaseModel):
    id: UUID
    actor_email: Optional[str] = None
    booking_id: Optional[UUID] = None
    action: str
    details: Optional[dict] = None
    created_at: datetime


class AdminBookingClearByDateIn(BaseModel):
    date: date


class AdminBookingBulkClearResultOut(BaseModel):
    deleted_count: int
    scope: str
    target_date: Optional[date] = None
    cutoff_time: Optional[datetime] = None


class RefundCreate(BaseModel):
    amount_cents: int
    reason: Optional[str] = None


class RefundOut(BaseModel):
    id: UUID
    booking_id: UUID
    admin_id: Optional[UUID] = None
    amount_cents: int
    currency: str
    status: str
    stripe_refund_id: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationLogOut(BaseModel):
    id: UUID
    user_id: Optional[UUID] = None
    booking_id: Optional[UUID] = None
    type: str
    status: str
    details: Optional[dict] = None
    sent_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ManualBookingCreate(BookingCreate):
    user_email: str
    full_name: Optional[str] = None


class AdminBookingLookupOut(BaseModel):
    id: UUID
    booking_kind: str = "room"
    room_id: Optional[UUID] = None
    staff_profile_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    start_time: datetime
    end_time: datetime
    duration_minutes: int
    original_price_cents: Optional[int] = None
    discount_cents: int = 0
    promo_code: Optional[str] = None
    tax_cents: int = 0
    price_cents: int
    currency: str
    status: str
    booking_code: str
    payment_intent_id: Optional[str] = None
    payment_expires_at: Optional[datetime] = None
    payment_seconds_remaining: Optional[int] = None
    confirmed_at: Optional[datetime] = None
    checked_in_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None
    note: Optional[str] = None
    staff_assignments: List[StaffOption] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    user_email: Optional[str] = None
    user_full_name: Optional[str] = None
    user_phone: Optional[str] = None
    room_name: Optional[str] = None
    staff_name: Optional[str] = None
    staff_photo_url: Optional[str] = None
    service_type: Optional[str] = None
    location_label: Optional[str] = None

    model_config = {"from_attributes": True}


class AdminTodayCounters(BaseModel):
    total: int = 0
    arrived: int = 0
    pending_arrival: int = 0
    cancelled: int = 0
    pending_payment: int = 0


class AdminTodayRosterOut(BaseModel):
    counters: AdminTodayCounters
    today: List[AdminBookingLookupOut] = Field(default_factory=list)
    tomorrow_first_three: List[AdminBookingLookupOut] = Field(default_factory=list)
    tomorrow_count: int = 0
    next_seven_days_count: int = 0
    generated_at: datetime
