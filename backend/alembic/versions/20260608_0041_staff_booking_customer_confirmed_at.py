"""add customer_confirmed_at to staff_bookings

Double-confirmation: a direct staff booking holds the slot from creation but is
only sent to the staff member once the customer confirms it. customer_confirmed_at
records that confirmation (NULL = awaiting the customer).

Revision ID: 20260608_0041
Revises: 20260604_0040
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0041"
down_revision: Union[str, None] = "20260604_0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "staff_bookings",
        sa.Column("customer_confirmed_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Existing bookings predate the confirmation step — treat them as already
    # confirmed so they keep behaving exactly as before.
    op.execute(
        "UPDATE staff_bookings SET customer_confirmed_at = COALESCE(responded_at, created_at) "
        "WHERE customer_confirmed_at IS NULL"
    )


def downgrade() -> None:
    op.drop_column("staff_bookings", "customer_confirmed_at")
