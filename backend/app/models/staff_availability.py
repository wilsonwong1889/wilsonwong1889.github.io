import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base


class StaffAvailabilityRule(Base):
    """A weekly recurring availability window for a staff member, e.g. Fridays
    2 PM-8 PM. Times are minutes-from-midnight in the business timezone."""

    __tablename__ = "staff_availability_rules"
    __table_args__ = (
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="staff_avail_rule_weekday_check"),
        CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute",
            name="staff_avail_rule_range_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 0 = Monday .. 6 = Sunday, matching datetime.weekday().
    weekday = Column(Integer, nullable=False)
    start_minute = Column(Integer, nullable=False)
    end_minute = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StaffAvailabilityException(Base):
    """A one-off override for a specific date: either a blocked window
    (is_available=False) or an extra-available window (is_available=True). A
    null time range means the whole day."""

    __tablename__ = "staff_availability_exceptions"
    __table_args__ = (
        CheckConstraint(
            "start_minute IS NULL OR (start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute)",
            name="staff_avail_exc_range_check",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    staff_profile_id = Column(
        UUID(as_uuid=True),
        ForeignKey("staff_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    exception_date = Column(Date, nullable=False, index=True)
    start_minute = Column(Integer)  # null = whole day
    end_minute = Column(Integer)
    is_available = Column(Boolean, nullable=False, default=False)
    reason = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
