from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class MembershipInterestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=3, max_length=40)
    membership_interest: str = Field(min_length=1, max_length=120)
    message: Optional[str] = Field(default=None, max_length=2000)


class ServiceInquiryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=3, max_length=40)
    service_interest: str = Field(min_length=1, max_length=120)
    message: Optional[str] = Field(default=None, max_length=2000)


class EngineerApplicationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=3, max_length=40)
    skillset: str = Field(min_length=1, max_length=2000)
    equipment: Optional[str] = Field(default=None, max_length=2000)
    why_considered: str = Field(min_length=1, max_length=2000)


class IntakeOut(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    intake_type: str
    name: str
    email: str
    phone: str
    details: dict
    status: str
    created_at: datetime


class IntakeStatusUpdate(BaseModel):
    status: str = Field(pattern="^(new|reviewed|archived)$")
