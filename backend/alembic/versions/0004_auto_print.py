"""auto-print default station

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_settings", sa.Column("auto_print_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "app_settings",
        sa.Column(
            "auto_print_station_id",
            sa.Integer(),
            sa.ForeignKey("print_stations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("app_settings", "auto_print_station_id")
    op.drop_column("app_settings", "auto_print_enabled")
