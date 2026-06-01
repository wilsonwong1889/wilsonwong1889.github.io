import uuid

from sqlalchemy import Boolean, Column, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from app.database import Base


class StaffProfile(Base):
    __tablename__ = "staff_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String)
    # Longer free-form biography (description stays a short service summary).
    bio = Column(String)
    skills = Column(JSONB, default=list)
    talents = Column(JSONB, default=list)
    # Showcase list of services offered (distinct from service_types, which is
    # the structured booking categorization synced onto rooms).
    services = Column(JSONB, default=list)
    photo_url = Column(String)
    # Additional headshot image URLs beyond the primary photo_url avatar.
    headshot_urls = Column(JSONB, default=list)
    portfolio_url = Column(String)
    add_on_price_cents = Column(Integer, nullable=False, default=0)
    booking_rate_cents = Column(Integer, nullable=False, default=0)
    equipment_rental_cost_cents = Column(Integer, nullable=False, default=0)
    service_types = Column(JSONB, default=list)
    booking_enabled = Column(Boolean, nullable=False, default=True)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
