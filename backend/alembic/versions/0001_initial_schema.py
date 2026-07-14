"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-07-14

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "print_stations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column(
            "connection_type",
            sa.Enum("lan_escpos", "usb_agent", name="station_connection_type"),
            nullable=False,
        ),
        sa.Column("lan_host", sa.String(255), nullable=True),
        sa.Column("lan_port", sa.Integer(), nullable=False, server_default="9100"),
        sa.Column("paper_width_cols", sa.Integer(), nullable=False, server_default="42"),
        sa.Column("codepage", sa.String(20), nullable=False, server_default="cp437"),
        sa.Column("api_key_hash", sa.String(255), nullable=True),
        sa.Column("api_key_prefix", sa.String(12), nullable=True),
        sa.Column("paired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "reservations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("external_ref", sa.String(200), nullable=True),
        sa.Column("source_channel", sa.String(100), nullable=False),
        sa.Column("parser_slug", sa.String(100), nullable=True),
        sa.Column("guest_name", sa.String(200), nullable=False),
        sa.Column("guest_email", sa.String(320), nullable=True),
        sa.Column("guest_phone", sa.String(50), nullable=True),
        sa.Column("checkin", sa.Date(), nullable=False),
        sa.Column("checkout", sa.Date(), nullable=False),
        sa.Column("room_type", sa.String(200), nullable=True),
        sa.Column("guests_adults", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("guests_children", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price_total", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column(
            "status",
            sa.Enum("pending", "confirmed", "cancelled", "manual", name="reservation_status"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("raw_source_text", sa.Text(), nullable=True),
        sa.Column("extra_fields", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "print_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "reservation_id",
            sa.Integer(),
            sa.ForeignKey("reservations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "station_id",
            sa.Integer(),
            sa.ForeignKey("print_stations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("queued", "sent", "printed", "failed", "cancelled", name="print_job_status"),
            nullable=False,
            server_default="queued",
        ),
        sa.Column("payload_text", sa.Text(), nullable=False),
        sa.Column("escpos_bytes", sa.LargeBinary(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("printed_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "admin_pins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("pin_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "parser_field_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("profile_slug", sa.String(100), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("match_subject_regex", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "parser_field_mapping_fields",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "mapping_id",
            sa.Integer(),
            sa.ForeignKey("parser_field_mappings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("target_field", sa.String(100), nullable=False),
        sa.Column(
            "extraction_type", sa.Enum("regex", "xpath", name="extraction_type"), nullable=False
        ),
        sa.Column("pattern", sa.Text(), nullable=False),
        sa.Column("group_index", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "transform",
            sa.Enum(
                "none",
                "strip",
                "parse_date_iso",
                "parse_date_eu",
                "parse_decimal",
                "upper",
                "lower",
                name="field_transform",
            ),
            nullable=False,
            server_default="none",
        ),
        sa.Column("is_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_table("parser_field_mapping_fields")
    op.drop_table("parser_field_mappings")
    op.drop_table("audit_log")
    op.drop_table("admin_pins")
    op.drop_table("print_jobs")
    op.drop_table("reservations")
    op.drop_table("print_stations")
    sa.Enum(name="extraction_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="field_transform").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="print_job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="reservation_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="station_connection_type").drop(op.get_bind(), checkfirst=True)
