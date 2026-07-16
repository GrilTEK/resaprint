"""add parse_date_long field transform

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-16

"""
from collections.abc import Sequence
from typing import Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres allows ADD VALUE inside a transaction since PG12, as
    # long as the new value isn't used in that same transaction — safe
    # here since it's only read/written by application code afterward.
    op.execute("ALTER TYPE field_transform ADD VALUE IF NOT EXISTS 'parse_date_long'")


def downgrade() -> None:
    # Postgres has no DROP VALUE for enum types; removing one requires
    # recreating the type (and repointing every column/dependency),
    # which isn't worth the risk for a downgrade path. Leaving the
    # unused value behind on downgrade is harmless.
    pass
