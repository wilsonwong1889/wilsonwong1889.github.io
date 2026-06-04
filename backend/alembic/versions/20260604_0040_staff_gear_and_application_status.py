"""add gear + application_status to staff_profiles

Supports self-service studio-engineer applications: applicants create an
account and fill out a full profile (gear is a new free-form field), which
sits as application_status="submitted" until an admin approves it.

Revision ID: 20260604_0040
Revises: 20260603_0039
Create Date: 2026-06-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260604_0040"
down_revision: Union[str, None] = "20260603_0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_profiles", sa.Column("gear", sa.String(), nullable=True))
    op.add_column("staff_profiles", sa.Column("application_status", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("staff_profiles", "application_status")
    op.drop_column("staff_profiles", "gear")
