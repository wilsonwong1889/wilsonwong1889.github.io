"""add unsubscribe_token to users

Adds an opaque per-user token used to build one-click CASL email unsubscribe
links. Backfills existing rows with unique UUIDs, then enforces a unique index.

Revision ID: 20260709_0044
Revises: 20260611_0043
Create Date: 2026-07-09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = "20260709_0044"
down_revision: Union[str, None] = "20260611_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.add_column("users", sa.Column("unsubscribe_token", UUID(as_uuid=True), nullable=True))
    # Backfill existing users with unique tokens.
    op.execute("UPDATE users SET unsubscribe_token = gen_random_uuid() WHERE unsubscribe_token IS NULL")
    op.create_unique_constraint("uq_users_unsubscribe_token", "users", ["unsubscribe_token"])


def downgrade() -> None:
    op.drop_constraint("uq_users_unsubscribe_token", "users", type_="unique")
    op.drop_column("users", "unsubscribe_token")
