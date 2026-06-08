import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, UUID

from app.config import settings
from app.database import Base


class StaffBooking(Base):
    __tablename__ = "staff_bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    staff_profile_id = Column(UUID(as_uuid=True), ForeignKey("staff_profiles.id", ondelete="CASCADE"), nullable=False)
    service_type = Column(String)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    original_price_cents = Column(Integer)
    discount_cents = Column(Integer, nullable=False, default=0)
    promo_code = Column(String)
    price_cents = Column(Integer, nullable=False)
    currency = Column(String, default=settings.DEFAULT_CURRENCY)
    status = Column(String, nullable=False, default="PendingPayment")
    booking_code = Column(String, nullable=False, unique=True)
    user_email_snapshot = Column(String)
    user_full_name_snapshot = Column(String)
    user_phone_snapshot = Column(String)
    payment_intent_id = Column(String)
    payment_client_secret = Column(String)
    confirmed_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(String)
    # When the staff member accepted/declined the request.
    responded_at = Column(DateTime(timezone=True))
    # When the customer confirmed (the double-confirmation step). The booking
    # holds the slot from creation, but is only sent to the staff member once
    # this is set. NULL = awaiting the customer's confirmation.
    customer_confirmed_at = Column(DateTime(timezone=True))
    note = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint(
            "status IN ('Requested','AcceptedPendingPayment','PendingPayment','Paid',"
            "'Completed','Declined','Expired','Cancelled','Refunded')",
            name="staff_booking_status_check",
        ),
        UniqueConstraint("payment_intent_id", name="uq_staff_bookings_payment_intent_id"),
        Index("ix_staff_bookings_profile_start_time", staff_profile_id, start_time),
        Index("ix_staff_bookings_status_start_time", status, start_time),
        Index("ix_staff_bookings_user_start_time", user_id, start_time),
        # A staff member can't be double-held: a Requested or accepted booking
        # blocks the slot just like a paid one.
        ExcludeConstraint(
            ("staff_profile_id", "="),
            (func.tstzrange(start_time, end_time, "[)"), "&&"),
            where=text(
                "status IN ('Requested','AcceptedPendingPayment','PendingPayment','Paid','Completed')"
            ),
            using="gist",
            name="staff_booking_time_excl",
        ),
    )

    @property
    def payment_expires_at(self):
        # The payment window opens once a request is accepted (or for legacy
        # PendingPayment bookings), anchored at the acceptance time.
        if self.status not in ("AcceptedPendingPayment", "PendingPayment"):
            return None
        anchor = self.responded_at if (self.status == "AcceptedPendingPayment" and self.responded_at) else self.created_at
        if not anchor:
            return None
        if anchor.tzinfo is None or anchor.utcoffset() is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return anchor + timedelta(minutes=settings.PENDING_BOOKING_EXPIRY_MINUTES)

    @property
    def request_expires_at(self):
        # The staff-response window only starts once the customer has confirmed
        # (when the request is actually sent to the staff member).
        if self.status != "Requested" or not self.customer_confirmed_at:
            return None
        anchor = self.customer_confirmed_at
        if anchor.tzinfo is None or anchor.utcoffset() is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        return anchor + timedelta(hours=settings.STAFF_REQUEST_EXPIRY_HOURS)

    @property
    def payment_seconds_remaining(self):
        expires_at = self.payment_expires_at
        if not expires_at:
            return None
        remaining = int((expires_at - datetime.now(timezone.utc)).total_seconds())
        return max(0, remaining)

    @property
    def user_email(self):
        if self.user_email_snapshot and not self.user_email_snapshot.endswith("@guest.studiobooking.local"):
            return self.user_email_snapshot
        return None

    @property
    def user_full_name(self):
        return self.user_full_name_snapshot

    @property
    def user_phone(self):
        return self.user_phone_snapshot
