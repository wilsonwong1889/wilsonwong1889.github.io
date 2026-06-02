from datetime import date
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class StaffAvailabilityRuleCreate(BaseModel):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday .. 6 = Sunday
    start_minute: int = Field(ge=0, le=1439)
    end_minute: int = Field(ge=1, le=1440)
    active: bool = True

    @model_validator(mode="after")
    def _check_range(self):
        if self.start_minute >= self.end_minute:
            raise ValueError("start_minute must be before end_minute")
        return self


class StaffAvailabilityRuleOut(BaseModel):
    id: UUID
    staff_profile_id: UUID
    weekday: int
    start_minute: int
    end_minute: int
    active: bool

    model_config = {"from_attributes": True}


class StaffAvailabilityExceptionCreate(BaseModel):
    exception_date: date
    start_minute: Optional[int] = Field(default=None, ge=0, le=1439)
    end_minute: Optional[int] = Field(default=None, ge=1, le=1440)
    is_available: bool = False
    reason: Optional[str] = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_range(self):
        if (self.start_minute is None) != (self.end_minute is None):
            raise ValueError("Provide both start_minute and end_minute, or neither for the whole day")
        if self.start_minute is not None and self.start_minute >= self.end_minute:
            raise ValueError("start_minute must be before end_minute")
        return self


class StaffAvailabilityExceptionOut(BaseModel):
    id: UUID
    staff_profile_id: UUID
    exception_date: date
    start_minute: Optional[int] = None
    end_minute: Optional[int] = None
    is_available: bool
    reason: Optional[str] = None

    model_config = {"from_attributes": True}


class ScheduleWindowOut(BaseModel):
    start_minute: int
    end_minute: int


class StaffDayScheduleOut(BaseModel):
    staff_profile_id: UUID
    name: str
    windows: List[ScheduleWindowOut] = []
