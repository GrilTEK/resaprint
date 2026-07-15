"""rooms + auto-assignment

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-15

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("room_number", sa.String(20), nullable=False, unique=True),
        sa.Column("category", sa.String(200), nullable=False),
        sa.Column("floor", sa.String(20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        "reservations",
        sa.Column("assigned_room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column(
        "reservation_room_lines",
        sa.Column("assigned_room_id", sa.Integer(), sa.ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reservation_room_lines", "assigned_room_id")
    op.drop_column("reservations", "assigned_room_id")
    op.drop_table("rooms")
