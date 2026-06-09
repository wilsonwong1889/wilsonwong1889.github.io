"""add instagram_url to staff_profiles

A staff member's public Instagram link, shown as an Instagram button on their
profile.

Revision ID: 20260608_0042
Revises: 20260608_0041
Create Date: 2026-06-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260608_0042"
down_revision: Union[str, None] = "20260608_0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_profiles", sa.Column("instagram_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_profiles", "instagram_url")
