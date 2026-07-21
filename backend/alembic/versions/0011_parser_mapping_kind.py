"""parser field mapping kind (reservation vs cancellation)

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-21

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    mapping_kind = sa.Enum("reservation", "cancellation", name="parser_mapping_kind")
    mapping_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "parser_field_mappings",
        sa.Column("kind", mapping_kind, nullable=False, server_default="reservation"),
    )


def downgrade() -> None:
    op.drop_column("parser_field_mappings", "kind")
    sa.Enum(name="parser_mapping_kind").drop(op.get_bind(), checkfirst=True)
