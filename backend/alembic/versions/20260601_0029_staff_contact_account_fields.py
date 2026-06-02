"""add contact + account + approval fields to staff_profiles

Supports the request-first staff booking flow: a linked login account
(user_id), notification routing (email/phone + channel toggles), a role title,
and whether bookings need this staff member's approval.

Revision ID: 20260601_0029
Revises: 20260601_0028
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260601_0029"
down_revision: Union[str, None] = "20260601_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("staff_profiles", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("staff_profiles", sa.Column("role_title", sa.String(), nullable=True))
    op.add_column("staff_profiles", sa.Column("notification_email", sa.String(), nullable=True))
    op.add_column("staff_profiles", sa.Column("notification_phone", sa.String(), nullable=True))
    op.add_column(
        "staff_profiles",
        sa.Column("notify_by_email", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column(
        "staff_profiles",
        sa.Column("notify_by_sms", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "staff_profiles",
        sa.Column("booking_requires_approval", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index(op.f("ix_staff_profiles_user_id"), "staff_profiles", ["user_id"])
    op.create_foreign_key(
        "fk_staff_profiles_user_id_users",
        "staff_profiles",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_staff_profiles_user_id_users", "staff_profiles", type_="foreignkey")
    op.drop_index(op.f("ix_staff_profiles_user_id"), table_name="staff_profiles")
    op.drop_column("staff_profiles", "booking_requires_approval")
    op.drop_column("staff_profiles", "notify_by_sms")
    op.drop_column("staff_profiles", "notify_by_email")
    op.drop_column("staff_profiles", "notification_phone")
    op.drop_column("staff_profiles", "notification_email")
    op.drop_column("staff_profiles", "role_title")
    op.drop_column("staff_profiles", "user_id")
