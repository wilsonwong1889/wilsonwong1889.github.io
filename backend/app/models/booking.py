import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    CheckConstraint,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB, UUID
from app.config import settings
from app.database import Base


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_minutes = Column(Integer, nullable=False)
    original_price_cents = Column(Integer)
    discount_cents = Column(Integer, nullable=False, default=0)
    promo_code = Column(String)
    tax_cents = Column(Integer, nullable=False, default=0)
    price_cents = Column(Integer, nullable=False)
    currency = Column(String, default=settings.DEFAULT_CURRENCY)
    status = Column(String, nullable=False, default="PendingPayment")
    booking_code = Column(String, nullable=False, unique=True)
    user_email_snapshot = Column(String)
    user_full_name_snapshot = Column(String)
    user_phone_snapshot = Column(String)
    room_name_snapshot = Column(String)
    room_description_snapshot = Column(String)
    payment_intent_id = Column(String)
    confirmed_at = Column(DateTime(timezone=True))
    checked_in_at = Column(DateTime(timezone=True))
    cancelled_at = Column(DateTime(timezone=True))
    cancellation_reason = Column(String)
    note = Column(String)
    deposit_amount_cents = Column(Integer, nullable=False, default=0)
    deposit_paid = Column(Boolean, nullable=False, default=False)
    deposit_with_engineer = Column(Boolean, nullable=False, default=False)
    staff_assignments = Column(JSONB, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        CheckConstraint(
            "status IN ('PendingPayment','Paid','DepositPaid','Completed','Cancelled','Refunded')",
            name="booking_status_check",
        ),
        UniqueConstraint("payment_intent_id", name="uq_bookings_payment_intent_id"),
        Index("ix_bookings_room_start_time", room_id, start_time),
        Index("ix_bookings_status_start_time", status, start_time),
        Index("ix_bookings_user_start_time", user_id, start_time),
        ExcludeConstraint(
            ("room_id", "="),
            (func.tstzrange(start_time, end_time, "[)"), "&&"),
            where=text("status IN ('PendingPayment','Paid','DepositPaid','Completed')"),
            using="gist",
            name="booking_room_time_excl",
        ),
    )

    @property
    def payment_expires_at(self):
        if self.status != "PendingPayment" or not self.created_at:
            return None
        created_at = self.created_at
        if created_at.tzinfo is None or created_at.utcoffset() is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return created_at + timedelta(minutes=settings.PENDING_BOOKING_EXPIRY_MINUTES)

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


class BookingSlot(Base):
    __tablename__ = "booking_slots"
    __table_args__ = (
        UniqueConstraint("room_id", "slot_start", name="uq_room_slot"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    slot_start = Column(DateTime(timezone=True), nullable=False)


class BookingStaffAssignment(Base):
    __tablename__ = "booking_staff_assignments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(
        UUID(as_uuid=True),
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False, index=True)
    staff_key = Column(String, nullable=False, index=True)
    staff_name = Column(String)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ExcludeConstraint(
            ("staff_key", "="),
            (func.tstzrange(start_time, end_time, "[)"), "&&"),
            using="gist",
            name="booking_staff_assignment_time_excl",
        ),
    )


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Requested','Processed','Rejected')",
            name="refund_status_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    amount_cents = Column(Integer, nullable=False)
    currency = Column(String, nullable=False, default=settings.DEFAULT_CURRENCY)
    status = Column(String, nullable=False, default="Requested")
    stripe_refund_id = Column(String)
    reason = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class NotificationLog(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (
        Index("ix_notification_logs_booking_type", "booking_id", "type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"))
    type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Queued")
    details = Column(JSONB)
    sent_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WebhookEventLog(Base):
    __tablename__ = "webhook_event_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('Processing','Processed','Failed')",
            name="webhook_event_log_status_check",
        ),
        UniqueConstraint("event_id", name="uq_webhook_event_logs_event_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Processing")
    attempt_count = Column(Integer, nullable=False, default=1)
    details = Column(JSONB)
    last_error = Column(String)
    processed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="review_rating_range_check"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    room_id = Column(UUID(as_uuid=True), ForeignKey("rooms.id", ondelete="CASCADE"), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"))
    booking_id = Column(UUID(as_uuid=True), ForeignKey("bookings.id", ondelete="SET NULL"))
    action = Column(String, nullable=False)
    details = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
