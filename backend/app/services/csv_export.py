"""CSV/ZIP export of the admin-visible tables, for the Settings » Export
page. Columns are an explicit allowlist per table (rather than every
model column) so secrets (PIN hashes, station API keys, the IMAP
password) and large raw payloads (escpos_bytes, raw source emails)
never end up in an exported file."""

import csv
import io
import json
import zipfile
from enum import Enum
from typing import Any, NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_pin import AdminPin
from app.models.audit_log import AuditLog
from app.models.print_job import PrintJob
from app.models.print_station import PrintStation
from app.models.reservation import Reservation
from app.models.reservation_room_line import ReservationRoomLine
from app.models.room import Room
from app.models.unparsed_email import UnparsedEmail


class ExportTable(NamedTuple):
    slug: str
    label: str
    model: type
    columns: tuple[str, ...]


EXPORT_TABLES: list[ExportTable] = [
    ExportTable(
        "reservations",
        "Reservations",
        Reservation,
        (
            "id", "external_ref", "source_channel", "parser_slug",
            "guest_name", "guest_email", "guest_phone",
            "checkin", "checkout", "room_type", "guests_adults", "guests_children",
            "price_total", "price_currency", "status", "assigned_room_id",
            "created_at", "updated_at",
        ),
    ),
    ExportTable(
        "reservation_room_lines",
        "Reservation room lines",
        ReservationRoomLine,
        (
            "id", "reservation_id", "sort_order", "room_type",
            "nights", "price_per_night", "price_total", "assigned_room_id",
        ),
    ),
    ExportTable(
        "rooms",
        "Rooms",
        Room,
        ("id", "room_number", "category", "floor", "notes", "is_active", "created_at", "updated_at"),
    ),
    ExportTable(
        "print_jobs",
        "Print jobs",
        PrintJob,
        (
            "id", "reservation_id", "station_id", "status", "attempts",
            "last_error", "requested_by", "created_at", "sent_at", "printed_at",
        ),
    ),
    ExportTable(
        "print_stations",
        "Print stations",
        PrintStation,
        (
            "id", "name", "connection_type", "lan_host", "lan_port",
            "paper_width_cols", "codepage", "paired_at", "is_active",
            "last_seen_at", "created_at", "updated_at",
        ),
    ),
    ExportTable(
        "users",
        "Users",
        AdminPin,
        (
            "id", "label", "role", "is_active", "failed_attempts",
            "locked_until", "last_login_at", "created_at", "updated_at",
        ),
    ),
    ExportTable(
        "audit_log",
        "Audit log",
        AuditLog,
        ("id", "actor", "action", "entity_type", "entity_id", "detail", "created_at"),
    ),
    ExportTable(
        "unparsed_emails",
        "Unparsed emails",
        UnparsedEmail,
        (
            "id", "subject", "content_type", "reason", "parser_slug",
            "status", "resolved_reservation_id", "created_at", "resolved_at",
        ),
    ),
]

_TABLES_BY_SLUG = {t.slug: t for t in EXPORT_TABLES}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


async def export_table_csv(db: AsyncSession, slug: str) -> str:
    """Renders one table as CSV text. Raises KeyError for an unknown slug."""
    table = _TABLES_BY_SLUG[slug]
    rows = (await db.execute(select(table.model).order_by(table.model.id))).scalars().all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(table.columns)
    for row in rows:
        writer.writerow([_cell(getattr(row, column)) for column in table.columns])
    return buffer.getvalue()


async def export_all_tables_zip(db: AsyncSession) -> bytes:
    """Bundles every exportable table into one ZIP of CSV files."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for table in EXPORT_TABLES:
            zf.writestr(f"{table.slug}.csv", await export_table_csv(db, table.slug))
    return buffer.getvalue()
