"""add room status check constraint

Revision ID: 20260602_0034
Revises: 20260602_0033
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260602_0034"
down_revision: Union[str, None] = "20260602_0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE rooms
        SET status = 'available'
        WHERE status IS NULL OR status NOT IN ('available', 'in_progress', 'tbc')
        """
    )
    op.create_check_constraint(
        "room_status_check",
        "rooms",
        "status IN ('available','in_progress','tbc')",
    )


def downgrade() -> None:
    op.drop_constraint("room_status_check", "rooms", type_="check")
