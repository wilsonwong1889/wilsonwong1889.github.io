import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class StaffBookingResponseToken(Base):
    """A one-time, hashed token backing a staff member's accept/decline link.

    Only the SHA-256 hash of the raw token is stored. A token is valid while it
    is unused and unexpired and its booking is still Requested.
    """

    __tablename__ = "staff_booking_response_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_booking_id = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
