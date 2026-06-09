from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.staffing import normalize_string_list


class StaffOption(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    add_on_price_cents: int = Field(default=0, ge=0)
    booking_rate_cents: int = Field(default=0, ge=0)
    photo_url: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    talents: List[str] = Field(default_factory=list)
    service_types: List[str] = Field(default_factory=list)
    booking_enabled: bool = True


class StaffProfileCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    bio: Optional[str] = Field(default=None, max_length=4000)
    skills: List[str] = Field(default_factory=list)
    talents: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    photo_url: Optional[str] = None
    headshot_urls: List[str] = Field(default_factory=list)
    portfolio_url: Optional[str] = Field(default=None, max_length=500)
    gear: Optional[str] = Field(default=None, max_length=2000)
    instagram_url: Optional[str] = Field(default=None, max_length=300)
    add_on_price_cents: int = Field(default=0, ge=0)
    booking_rate_cents: int = Field(default=0, ge=0)
    equipment_rental_cost_cents: int = Field(default=0, ge=0)
    service_types: List[str] = Field(default_factory=list)
    role_title: Optional[str] = Field(default=None, max_length=120)
    notification_email: Optional[str] = Field(default=None, max_length=120)
    notification_phone: Optional[str] = Field(default=None, max_length=40)
    notify_by_email: bool = True
    notify_by_sms: bool = False
    booking_requires_approval: bool = True
    # Links the staff login account by email and grants the Staff role.
    linked_user_email: Optional[str] = Field(default=None, max_length=120)
    booking_enabled: bool = True
    schedule_published: bool = False
    active: bool = True

    @field_validator("skills", "talents", "service_types", "services", "headshot_urls", mode="before")
    @classmethod
    def normalize_lists(cls, value):
        return normalize_string_list(value)


class StaffProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    bio: Optional[str] = Field(default=None, max_length=4000)
    skills: Optional[List[str]] = None
    talents: Optional[List[str]] = None
    services: Optional[List[str]] = None
    photo_url: Optional[str] = None
    headshot_urls: Optional[List[str]] = None
    portfolio_url: Optional[str] = Field(default=None, max_length=500)
    gear: Optional[str] = Field(default=None, max_length=2000)
    instagram_url: Optional[str] = Field(default=None, max_length=300)
    add_on_price_cents: Optional[int] = Field(default=None, ge=0)
    booking_rate_cents: Optional[int] = Field(default=None, ge=0)
    equipment_rental_cost_cents: Optional[int] = Field(default=None, ge=0)
    service_types: Optional[List[str]] = None
    role_title: Optional[str] = Field(default=None, max_length=120)
    notification_email: Optional[str] = Field(default=None, max_length=120)
    notification_phone: Optional[str] = Field(default=None, max_length=40)
    notify_by_email: Optional[bool] = None
    notify_by_sms: Optional[bool] = None
    booking_requires_approval: Optional[bool] = None
    linked_user_email: Optional[str] = Field(default=None, max_length=120)
    booking_enabled: Optional[bool] = None
    schedule_published: Optional[bool] = None
    active: Optional[bool] = None

    @field_validator("skills", "talents", "service_types", "services", "headshot_urls", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value):
        if value is None:
            return value
        return normalize_string_list(value)


class StaffSelfProfileUpdate(BaseModel):
    """Fields a staff member may edit on their OWN profile. Deliberately omits
    pricing, schedule_published, linked_user_email, booking_enabled, active and
    booking_requires_approval — those stay admin-only."""

    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    description: Optional[str] = Field(default=None, max_length=500)
    bio: Optional[str] = Field(default=None, max_length=4000)
    skills: Optional[List[str]] = None
    talents: Optional[List[str]] = None
    services: Optional[List[str]] = None
    photo_url: Optional[str] = None
    headshot_urls: Optional[List[str]] = None
    portfolio_url: Optional[str] = Field(default=None, max_length=500)
    gear: Optional[str] = Field(default=None, max_length=2000)
    instagram_url: Optional[str] = Field(default=None, max_length=300)
    service_types: Optional[List[str]] = None
    role_title: Optional[str] = Field(default=None, max_length=120)
    notification_email: Optional[str] = Field(default=None, max_length=120)
    notification_phone: Optional[str] = Field(default=None, max_length=40)
    notify_by_email: Optional[bool] = None
    notify_by_sms: Optional[bool] = None

    model_config = {"extra": "forbid"}

    @field_validator("skills", "talents", "service_types", "services", "headshot_urls", mode="before")
    @classmethod
    def normalize_optional_lists(cls, value):
        if value is None:
            return value
        return normalize_string_list(value)


class StaffProfileOut(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    bio: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    talents: List[str] = Field(default_factory=list)
    services: List[str] = Field(default_factory=list)
    photo_url: Optional[str] = None
    headshot_urls: List[str] = Field(default_factory=list)
    portfolio_url: Optional[str] = None
    gear: Optional[str] = None
    instagram_url: Optional[str] = None
    add_on_price_cents: int
    booking_rate_cents: int
    equipment_rental_cost_cents: int = 0
    service_types: List[str] = Field(default_factory=list)
    user_id: Optional[UUID] = None
    role_title: Optional[str] = None
    notification_email: Optional[str] = None
    notification_phone: Optional[str] = None
    notify_by_email: bool = True
    notify_by_sms: bool = False
    booking_requires_approval: bool = True
    booking_enabled: bool
    schedule_published: bool = False
    application_status: Optional[str] = None
    active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("skills", "talents", "service_types", "services", "headshot_urls", mode="before")
    @classmethod
    def normalize_output_lists(cls, value):
        return normalize_string_list(value)

    model_config = {"from_attributes": True}


class AdminStaffProfileOut(StaffProfileOut):
    linked_user_email: Optional[str] = None


class StaffApplicationStateOut(BaseModel):
    """What the staff dashboard needs to choose between applicant mode and the
    full staff portal."""

    is_staff: bool = False
    profile: Optional[StaffProfileOut] = None


class StaffPhotoUploadOut(BaseModel):
    photo_url: str
