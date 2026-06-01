"""add showcase fields to staff_profiles

Adds bio, services, headshot_urls, portfolio_url, and equipment_rental_cost_cents
so a staff/engineer profile can carry a fuller public showcase.

Revision ID: 20260601_0026
Revises: 20260601_0025
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260601_0026"
down_revision: Union[str, None] = "20260601_0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_profiles", sa.Column("bio", sa.String(), nullable=True))
    op.add_column("staff_profiles", sa.Column("portfolio_url", sa.String(), nullable=True))
    op.add_column(
        "staff_profiles",
        sa.Column("services", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "staff_profiles",
        sa.Column("headshot_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "staff_profiles",
        sa.Column(
            "equipment_rental_cost_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("staff_profiles", "equipment_rental_cost_cents")
    op.drop_column("staff_profiles", "headshot_urls")
    op.drop_column("staff_profiles", "services")
    op.drop_column("staff_profiles", "portfolio_url")
    op.drop_column("staff_profiles", "bio")
