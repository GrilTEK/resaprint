"""reservation room lines + parser room_line_pattern

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-14

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("parser_field_mappings", sa.Column("room_line_pattern", sa.Text(), nullable=True))

    op.create_table(
        "reservation_room_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reservation_id",
            sa.Integer(),
            sa.ForeignKey("reservations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("room_type", sa.String(200), nullable=False),
        sa.Column("nights", sa.Integer(), nullable=True),
        sa.Column("price_per_night", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_total", sa.Numeric(10, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("reservation_room_lines")
    op.drop_column("parser_field_mappings", "room_line_pattern")
