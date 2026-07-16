"""unparsed emails (reparse support)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-16

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "unparsed_emails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("parser_slug", sa.String(100), nullable=True),
        sa.Column(
            "status",
            sa.Enum("pending", "resolved", "ignored", name="unparsed_email_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "resolved_reservation_id",
            sa.Integer(),
            sa.ForeignKey("reservations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("unparsed_emails")
    sa.Enum(name="unparsed_email_status").drop(op.get_bind(), checkfirst=True)
