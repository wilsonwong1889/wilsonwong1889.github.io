"""add deposit_cents to rooms

Per-room booking deposit, separate from the hourly rate. Defaults to $20
(2000 cents); admins can change it per room.

Revision ID: 20260601_0028
Revises: 20260601_0027
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260601_0028"
down_revision: Union[str, None] = "20260601_0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column("deposit_cents", sa.Integer(), nullable=False, server_default="2000"),
    )


def downgrade() -> None:
    op.drop_column("rooms", "deposit_cents")
