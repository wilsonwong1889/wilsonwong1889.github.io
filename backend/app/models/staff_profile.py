import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.database import Base


class StaffProfile(Base):
    __tablename__ = "staff_profiles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    description = Column(String)
    # Optional linked login account for this staff member (so engineers can log
    # in to a staff portal). Set via the admin "linked account email" field.
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user = relationship("User")

    @property
    def linked_user_email(self):
        return self.user.email if self.user else None

    role_title = Column(String)
    # Where booking-request notifications go (falls back to the linked account).
    notification_email = Column(String)
    notification_phone = Column(String)
    notify_by_email = Column(Boolean, nullable=False, default=True)
    notify_by_sms = Column(Boolean, nullable=False, default=False)
    # When true, staff bookings start as Requested and need this staff member's
    # approval before payment; when false they go straight to PendingPayment.
    booking_requires_approval = Column(Boolean, nullable=False, default=True)
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
    # Public Instagram profile URL (shown as an Instagram button on the profile).
    instagram_url = Column(String)
    # Free-form list of equipment/gear the engineer works with.
    gear = Column(String)
    # Self-service application workflow: NULL for admin-created profiles,
    # "submitted" while awaiting admin review, "approved" once granted staff.
    application_status = Column(String)
    add_on_price_cents = Column(Integer, nullable=False, default=0)
    booking_rate_cents = Column(Integer, nullable=False, default=0)
    equipment_rental_cost_cents = Column(Integer, nullable=False, default=0)
    service_types = Column(JSONB, default=list)
    booking_enabled = Column(Boolean, nullable=False, default=True)
    # When true, the admin has published this staff member's schedule so the
    # public can see availability and request to book them.
    schedule_published = Column(Boolean, nullable=False, default=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
