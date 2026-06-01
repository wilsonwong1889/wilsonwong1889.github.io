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
    add_on_price_cents: int = Field(default=0, ge=0)
    booking_rate_cents: int = Field(default=0, ge=0)
    equipment_rental_cost_cents: int = Field(default=0, ge=0)
    service_types: List[str] = Field(default_factory=list)
    booking_enabled: bool = True
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
    add_on_price_cents: Optional[int] = Field(default=None, ge=0)
    booking_rate_cents: Optional[int] = Field(default=None, ge=0)
    equipment_rental_cost_cents: Optional[int] = Field(default=None, ge=0)
    service_types: Optional[List[str]] = None
    booking_enabled: Optional[bool] = None
    active: Optional[bool] = None

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
    add_on_price_cents: int
    booking_rate_cents: int
    equipment_rental_cost_cents: int = 0
    service_types: List[str] = Field(default_factory=list)
    booking_enabled: bool
    active: bool
    created_at: datetime
    updated_at: Optional[datetime] = None

    @field_validator("skills", "talents", "service_types", "services", "headshot_urls", mode="before")
    @classmethod
    def normalize_output_lists(cls, value):
        return normalize_string_list(value)

    model_config = {"from_attributes": True}


class StaffPhotoUploadOut(BaseModel):
    photo_url: str
