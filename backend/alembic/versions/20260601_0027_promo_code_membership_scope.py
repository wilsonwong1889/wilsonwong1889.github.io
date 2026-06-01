"""add membership scoping to promo_codes

Supports per-member monthly coupon codes: member_category scope, a
member_unique flag, the assigned member (assigned_user_id), and the
valid_month the code was issued for.

Revision ID: 20260601_0027
Revises: 20260601_0026
Create Date: 2026-06-01
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260601_0027"
down_revision: Union[str, None] = "20260601_0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("promo_codes", sa.Column("member_category", sa.String(), nullable=True))
    op.add_column(
        "promo_codes",
        sa.Column("member_unique", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "promo_codes",
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("promo_codes", sa.Column("valid_month", sa.String(), nullable=True))
    op.create_index(op.f("ix_promo_codes_member_category"), "promo_codes", ["member_category"])
    op.create_index(op.f("ix_promo_codes_assigned_user_id"), "promo_codes", ["assigned_user_id"])
    op.create_foreign_key(
        "fk_promo_codes_assigned_user_id_users",
        "promo_codes",
        "users",
        ["assigned_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_promo_codes_assigned_user_id_users", "promo_codes", type_="foreignkey")
    op.drop_index(op.f("ix_promo_codes_assigned_user_id"), table_name="promo_codes")
    op.drop_index(op.f("ix_promo_codes_member_category"), table_name="promo_codes")
    op.drop_column("promo_codes", "valid_month")
    op.drop_column("promo_codes", "assigned_user_id")
    op.drop_column("promo_codes", "member_unique")
    op.drop_column("promo_codes", "member_category")
