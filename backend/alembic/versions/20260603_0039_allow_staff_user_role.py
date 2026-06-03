"""allow Staff user role

Revision ID: 20260603_0039
Revises: 20260603_0038
Create Date: 2026-06-03
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260603_0039"
down_revision: Union[str, None] = "20260603_0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("user_role_check", "users", type_="check")
    op.create_check_constraint(
        "user_role_check",
        "users",
        "role IN ('Customer','Staff','Admin','AdminManager')",
    )


def downgrade() -> None:
    op.drop_constraint("user_role_check", "users", type_="check")
    op.execute("UPDATE users SET role = 'Customer' WHERE role = 'Staff'")
    op.create_check_constraint(
        "user_role_check",
        "users",
        "role IN ('Customer','Admin','AdminManager')",
    )
