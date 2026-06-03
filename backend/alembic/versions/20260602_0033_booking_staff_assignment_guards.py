"""add room booking staff assignment guards

Revision ID: 20260602_0033
Revises: 20260602_0032
Create Date: 2026-06-02
"""
from __future__ import annotations

import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260602_0033"
down_revision: Union[str, None] = "20260602_0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "booking_staff_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("room_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_key", sa.String(), nullable=False),
        sa.Column("staff_name", sa.String(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["booking_id"], ["bookings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_booking_staff_assignments_booking_id"),
        "booking_staff_assignments",
        ["booking_id"],
    )
    op.create_index(
        op.f("ix_booking_staff_assignments_room_id"),
        "booking_staff_assignments",
        ["room_id"],
    )
    op.create_index(
        op.f("ix_booking_staff_assignments_staff_key"),
        "booking_staff_assignments",
        ["staff_key"],
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT id, room_id, start_time, end_time, staff_assignments
            FROM bookings
            WHERE status IN ('PendingPayment', 'Paid', 'Completed')
              AND staff_assignments IS NOT NULL
              AND jsonb_array_length(staff_assignments::jsonb) > 0
            """
        )
    ).mappings()
    for row in rows:
        for assignment in row["staff_assignments"] or []:
            staff_key = str(assignment.get("id") or "").strip()
            if not staff_key:
                continue
            bind.execute(
                sa.text(
                    """
                    INSERT INTO booking_staff_assignments (
                        id, booking_id, room_id, staff_key, staff_name, start_time, end_time
                    )
                    VALUES (
                        :id, :booking_id, :room_id, :staff_key, :staff_name, :start_time, :end_time
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "booking_id": row["id"],
                    "room_id": row["room_id"],
                    "staff_key": staff_key,
                    "staff_name": assignment.get("name") or staff_key,
                    "start_time": row["start_time"],
                    "end_time": row["end_time"],
                },
            )

    op.execute(
        """
        ALTER TABLE booking_staff_assignments
        ADD CONSTRAINT booking_staff_assignment_time_excl
        EXCLUDE USING gist (
          staff_key WITH =,
          tstzrange(start_time, end_time, '[)') WITH &&
        )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE booking_staff_assignments DROP CONSTRAINT IF EXISTS booking_staff_assignment_time_excl")
    op.drop_index(
        op.f("ix_booking_staff_assignments_staff_key"),
        table_name="booking_staff_assignments",
    )
    op.drop_index(
        op.f("ix_booking_staff_assignments_room_id"),
        table_name="booking_staff_assignments",
    )
    op.drop_index(
        op.f("ix_booking_staff_assignments_booking_id"),
        table_name="booking_staff_assignments",
    )
    op.drop_table("booking_staff_assignments")
