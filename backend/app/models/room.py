import uuid
from sqlalchemy import CheckConstraint, Column, String, Integer, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base

class Room(Base):
    __tablename__ = "rooms"
    __table_args__ = (
        CheckConstraint(
            "status IN ('available','in_progress','tbc')",
            name="room_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String)
    capacity = Column(Integer)
    photos = Column(JSONB, default=list)
    staff_roles = Column(JSONB, default=list)
    hourly_rate_cents = Column(Integer, nullable=False, default=5000)
    # Booking deposit for this room, separate from the hourly rate. Defaults to
    # $20 (2000 cents); admins can set it per room.
    deposit_cents = Column(Integer, nullable=False, default=2000)
    max_booking_duration_minutes = Column(Integer, nullable=False, default=300)
    active = Column(Boolean, default=True)
    coming_soon = Column(Boolean, default=False)
    status = Column(String(32), default="available")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
