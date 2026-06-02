"""request-first staff booking states

Adds the request-first lifecycle: new statuses (Requested,
AcceptedPendingPayment, Declined, Expired), a responded_at timestamp, and an
expanded status check + overlap-exclusion constraint so a Requested or
accepted booking holds the slot.

Revision ID: 20260602_0031
Revises: 20260601_0030
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260602_0031"
down_revision: Union[str, None] = "20260601_0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_STATUSES = (
    "'Requested','AcceptedPendingPayment','PendingPayment','Paid',"
    "'Completed','Declined','Expired','Cancelled','Refunded'"
)
_OLD_STATUSES = "'PendingPayment','Paid','Completed','Cancelled','Refunded'"
_NEW_ACTIVE = "'Requested','AcceptedPendingPayment','PendingPayment','Paid','Completed'"
_OLD_ACTIVE = "'PendingPayment','Paid','Completed'"


def _swap_constraints(status_values: str, active_values: str) -> None:
    op.drop_constraint("staff_booking_status_check", "staff_bookings", type_="check")
    op.create_check_constraint(
        "staff_booking_status_check", "staff_bookings", f"status IN ({status_values})"
    )
    op.execute("ALTER TABLE staff_bookings DROP CONSTRAINT IF EXISTS staff_booking_time_excl")
    op.execute(
        f"""
        ALTER TABLE staff_bookings
        ADD CONSTRAINT staff_booking_time_excl
        EXCLUDE USING gist (
          staff_profile_id WITH =,
          tstzrange(start_time, end_time, '[)') WITH &&
        )
        WHERE (status IN ({active_values}))
        """
    )


def upgrade() -> None:
    op.add_column("staff_bookings", sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True))
    _swap_constraints(_NEW_STATUSES, _NEW_ACTIVE)


def downgrade() -> None:
    _swap_constraints(_OLD_STATUSES, _OLD_ACTIVE)
    op.drop_column("staff_bookings", "responded_at")
