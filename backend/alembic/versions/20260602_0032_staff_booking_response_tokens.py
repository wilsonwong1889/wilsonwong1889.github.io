"""create staff_booking_response_tokens

One-time hashed accept/decline tokens for the staff request links.

Revision ID: 20260602_0032
Revises: 20260602_0031
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260602_0032"
down_revision: Union[str, None] = "20260602_0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "staff_booking_response_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("staff_booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["staff_booking_id"], ["staff_bookings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_staff_booking_response_tokens_staff_booking_id"),
        "staff_booking_response_tokens",
        ["staff_booking_id"],
    )
    op.create_index(
        op.f("ix_staff_booking_response_tokens_token_hash"),
        "staff_booking_response_tokens",
        ["token_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_staff_booking_response_tokens_token_hash"),
        table_name="staff_booking_response_tokens",
    )
    op.drop_index(
        op.f("ix_staff_booking_response_tokens_staff_booking_id"),
        table_name="staff_booking_response_tokens",
    )
    op.drop_table("staff_booking_response_tokens")
