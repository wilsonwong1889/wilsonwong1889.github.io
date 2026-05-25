"""add room_name_snapshot + room_description_snapshot to bookings

Snapshots the room name and description on the booking row at create-time
so that renaming or archiving a room later doesn't retroactively rewrite
the customer's booking history.

Revision ID: 20260525_0024
Revises: 20260520_0023
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa


revision = "20260525_0024"
down_revision = "20260520_0023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("bookings", sa.Column("room_name_snapshot", sa.String(), nullable=True))
    op.add_column("bookings", sa.Column("room_description_snapshot", sa.String(), nullable=True))

    # Backfill existing rows from the rooms table so historical bookings keep
    # whatever name was attached at the moment of this migration.
    op.execute(
        """
        UPDATE bookings AS b
        SET
            room_name_snapshot = r.name,
            room_description_snapshot = r.description
        FROM rooms AS r
        WHERE b.room_id = r.id
          AND b.room_name_snapshot IS NULL
        """
    )


def downgrade():
    op.drop_column("bookings", "room_description_snapshot")
    op.drop_column("bookings", "room_name_snapshot")
