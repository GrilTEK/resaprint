"""receipt layout settings

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_settings", sa.Column("receipt_font", sa.String(10), nullable=False, server_default="font_a"))
    op.add_column(
        "app_settings", sa.Column("receipt_font_size", sa.String(10), nullable=False, server_default="normal")
    )
    op.add_column(
        "app_settings", sa.Column("receipt_bold_labels", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "app_settings", sa.Column("receipt_show_nights", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "app_settings", sa.Column("receipt_show_guests", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "app_settings", sa.Column("receipt_show_channel", sa.Boolean(), nullable=False, server_default=sa.true())
    )


def downgrade() -> None:
    op.drop_column("app_settings", "receipt_show_channel")
    op.drop_column("app_settings", "receipt_show_guests")
    op.drop_column("app_settings", "receipt_show_nights")
    op.drop_column("app_settings", "receipt_bold_labels")
    op.drop_column("app_settings", "receipt_font_size")
    op.drop_column("app_settings", "receipt_font")
