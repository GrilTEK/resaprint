"""admin pin roles

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-15

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    admin_role = sa.Enum("admin", "reception", name="admin_role")
    admin_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "admin_pins",
        sa.Column("role", admin_role, nullable=False, server_default="admin"),
    )


def downgrade() -> None:
    op.drop_column("admin_pins", "role")
    sa.Enum(name="admin_role").drop(op.get_bind(), checkfirst=True)
