"""add booking query indexes

Revision ID: 20260602_0037
Revises: 20260602_0036
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20260602_0037"
down_revision: Union[str, None] = "20260602_0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_bookings_room_start_time", "bookings", ["room_id", "start_time"])
    op.create_index("ix_bookings_status_start_time", "bookings", ["status", "start_time"])
    op.create_index("ix_bookings_user_start_time", "bookings", ["user_id", "start_time"])
    op.create_index(
        "ix_staff_bookings_profile_start_time",
        "staff_bookings",
        ["staff_profile_id", "start_time"],
    )
    op.create_index(
        "ix_staff_bookings_status_start_time",
        "staff_bookings",
        ["status", "start_time"],
    )
    op.create_index(
        "ix_staff_bookings_user_start_time",
        "staff_bookings",
        ["user_id", "start_time"],
    )
    op.create_index(
        "ix_notification_logs_booking_type",
        "notification_logs",
        ["booking_id", "type"],
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_index("ix_notification_logs_booking_type", table_name="notification_logs")
    op.drop_index("ix_staff_bookings_user_start_time", table_name="staff_bookings")
    op.drop_index("ix_staff_bookings_status_start_time", table_name="staff_bookings")
    op.drop_index("ix_staff_bookings_profile_start_time", table_name="staff_bookings")
    op.drop_index("ix_bookings_user_start_time", table_name="bookings")
    op.drop_index("ix_bookings_status_start_time", table_name="bookings")
    op.drop_index("ix_bookings_room_start_time", table_name="bookings")
