"""add DepositPaid status to bookings

Adds the 'DepositPaid' status (deposit collected, balance still owing) to the
bookings status check constraint, and includes it in the room/time overlap
exclusion guard so a deposit-paid booking still holds its slot (no double-book).

Revision ID: 20260611_0043
Revises: 20260608_0042
Create Date: 2026-06-11
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260611_0043"
down_revision: Union[str, None] = "20260608_0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_STATUSES = "'PendingPayment','Paid','DepositPaid','Completed','Cancelled','Refunded'"
_OLD_STATUSES = "'PendingPayment','Paid','Completed','Cancelled','Refunded'"
_NEW_EXCL = "'PendingPayment','Paid','DepositPaid','Completed'"
_OLD_EXCL = "'PendingPayment','Paid','Completed'"


def _apply(status_values: str, excl_values: str) -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.drop_constraint("booking_status_check", "bookings", type_="check")
    op.create_check_constraint(
        "booking_status_check", "bookings", f"status IN ({status_values})"
    )
    op.execute("ALTER TABLE bookings DROP CONSTRAINT IF EXISTS booking_room_time_excl")
    op.execute(
        f"""
        ALTER TABLE bookings
        ADD CONSTRAINT booking_room_time_excl
        EXCLUDE USING gist (
          room_id WITH =,
          tstzrange(start_time, end_time, '[)') WITH &&
        )
        WHERE (status IN ({excl_values}))
        """
    )


def upgrade() -> None:
    _apply(_NEW_STATUSES, _NEW_EXCL)


def downgrade() -> None:
    # Revert any DepositPaid rows so the tighter constraint re-applies cleanly.
    op.execute("UPDATE bookings SET status = 'Paid' WHERE status = 'DepositPaid'")
    _apply(_OLD_STATUSES, _OLD_EXCL)
