"""create staff availability rules + exceptions

Weekly recurring availability (staff_availability_rules) and one-off
unavailable/extra-available blocks (staff_availability_exceptions). Times are
minutes-from-midnight in the business timezone.

Revision ID: 20260601_0030
Revises: 20260601_0029
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260601_0030"
down_revision: Union[str, None] = "20260601_0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_availability_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint("weekday >= 0 AND weekday <= 6", name="staff_avail_rule_weekday_check"),
        sa.CheckConstraint(
            "start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute",
            name="staff_avail_rule_range_check",
        ),
        sa.ForeignKeyConstraint(["staff_profile_id"], ["staff_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_staff_availability_rules_staff_profile_id"),
        "staff_availability_rules",
        ["staff_profile_id"],
    )

    op.create_table(
        "staff_availability_exceptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exception_date", sa.Date(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=True),
        sa.Column("end_minute", sa.Integer(), nullable=True),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.CheckConstraint(
            "start_minute IS NULL OR (start_minute >= 0 AND end_minute <= 1440 AND start_minute < end_minute)",
            name="staff_avail_exc_range_check",
        ),
        sa.ForeignKeyConstraint(["staff_profile_id"], ["staff_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_staff_availability_exceptions_staff_profile_id"),
        "staff_availability_exceptions",
        ["staff_profile_id"],
    )
    op.create_index(
        op.f("ix_staff_availability_exceptions_exception_date"),
        "staff_availability_exceptions",
        ["exception_date"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_staff_availability_exceptions_exception_date"),
        table_name="staff_availability_exceptions",
    )
    op.drop_index(
        op.f("ix_staff_availability_exceptions_staff_profile_id"),
        table_name="staff_availability_exceptions",
    )
    op.drop_table("staff_availability_exceptions")
    op.drop_index(
        op.f("ix_staff_availability_rules_staff_profile_id"),
        table_name="staff_availability_rules",
    )
    op.drop_table("staff_availability_rules")
