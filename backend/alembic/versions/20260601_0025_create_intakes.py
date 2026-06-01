"""create intakes table

Backs the public membership-interest and studio-engineer-application forms.
One table, discriminated by ``intake_type``, with type-specific answers in
``details``.

Revision ID: 20260601_0025
Revises: 20260525_0024
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260601_0025"
down_revision: Union[str, None] = "20260525_0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "intakes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("intake_type", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_intakes_intake_type"), "intakes", ["intake_type"], unique=False)
    op.create_index(op.f("ix_intakes_status"), "intakes", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_intakes_status"), table_name="intakes")
    op.drop_index(op.f("ix_intakes_intake_type"), table_name="intakes")
    op.drop_table("intakes")
