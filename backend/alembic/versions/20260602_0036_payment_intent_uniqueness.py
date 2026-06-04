"""add payment intent uniqueness guards

Revision ID: 20260602_0036
Revises: 20260602_0035
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260602_0036"
down_revision: Union[str, None] = "20260602_0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_bookings_payment_intent_id",
        "bookings",
        ["payment_intent_id"],
    )
    op.create_unique_constraint(
        "uq_staff_bookings_payment_intent_id",
        "staff_bookings",
        ["payment_intent_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_staff_bookings_payment_intent_id", "staff_bookings", type_="unique")
    op.drop_constraint("uq_bookings_payment_intent_id", "bookings", type_="unique")
