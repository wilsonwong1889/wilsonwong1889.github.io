"""add schedule_published to staff_profiles

Admin-controlled flag: when true the staff member's schedule is published so
the public can see availability and request to book them.

Revision ID: 20260603_0038
Revises: 20260602_0037
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260603_0038"
down_revision: Union[str, None] = "20260602_0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "staff_profiles",
        sa.Column("schedule_published", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("staff_profiles", "schedule_published")
