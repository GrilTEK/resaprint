"""app_settings table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("imap_host", sa.String(255), nullable=True),
        sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"),
        sa.Column("imap_user", sa.String(255), nullable=True),
        sa.Column("imap_password_encrypted", sa.Text(), nullable=True),
        sa.Column("imap_folder", sa.String(255), nullable=False, server_default="INBOX"),
        sa.Column("imap_processed_folder", sa.String(255), nullable=False, server_default="Processed"),
        sa.Column("imap_poll_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
