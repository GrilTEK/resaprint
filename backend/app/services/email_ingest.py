"""IMAP reservation-email ingestion.

Uses stdlib `imaplib` (no third-party IMAP dependency — "boring
libraries"), run in a thread executor since imaplib is synchronous.
Polls a single configurable folder for UNSEEN messages, dispatches
each to the parser registry, and either creates a Reservation (moving
the message to the processed folder) or logs an `email.unparsed` audit
entry (leaving the message in place, marked \\Seen so it isn't
reprocessed every poll).

Connection settings (host/user/password/folders/poll interval) are
read from the AppSettings DB row (editable from the admin UI's
Settings page, seeded from backend/.env on first access) rather than
static config — so changing them takes effect on the next poll with no
restart needed.
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from dataclasses import dataclass
from email.message import Message

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db import async_session_maker
from app.models.parser_mapping import ParserFieldMapping
from app.models.print_station import PrintStation
from app.models.reservation import Reservation, ReservationStatus
from app.models.reservation_room_line import ReservationRoomLine
from app.models.unparsed_email import UnparsedEmail
from app.schemas.parser import ParsedReservation
from app.services import audit, printing
from app.services.app_settings import get_or_create_settings
from app.services.crypto import decrypt
from app.services.parser_registry import GenericFieldMappingParser, ParserError, ParserRegistry
from app.services.parsers.reference_booking_com import ReferenceBookingComParser
from app.services.room_assignment import assign_rooms_for_reservation

logger = logging.getLogger("resaprint.email_ingest")

DEFAULT_POLL_SECONDS = 60


@dataclass
class ImapConnectionInfo:
    host: str
    port: int
    user: str
    password: str
    folder: str
    processed_folder: str


@dataclass
class FetchedEmail:
    uid: bytes
    subject: str
    body: str
    content_type: str


async def load_imap_connection_info(db: AsyncSession) -> ImapConnectionInfo | None:
    row = await get_or_create_settings(db)
    if not row.imap_host or not row.imap_user or not row.imap_password_encrypted:
        return None
    return ImapConnectionInfo(
        host=row.imap_host,
        port=row.imap_port,
        user=row.imap_user,
        password=decrypt(row.imap_password_encrypted),
        folder=row.imap_folder,
        processed_folder=row.imap_processed_folder,
    )


def _decode_subject(msg: Message) -> str:
    from email.header import decode_header

    parts = decode_header(msg.get("Subject") or "")
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += text.decode(charset or "utf-8", errors="replace")
        else:
            decoded += text
    return decoded


def _extract_body(msg: Message) -> tuple[str, str]:
    if msg.is_multipart():
        html_part, text_part = None, None
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain" and text_part is None:
                text_part = part
            elif content_type == "text/html" and html_part is None:
                html_part = part
        chosen = text_part or html_part
        if chosen is None:
            return "", "text/plain"
        payload = chosen.get_payload(decode=True) or b""
        charset = chosen.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace"), chosen.get_content_type()

    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace"), msg.get_content_type()


def _fetch_unseen_sync(conn_info: ImapConnectionInfo) -> list[FetchedEmail]:
    conn = imaplib.IMAP4_SSL(conn_info.host, conn_info.port)
    try:
        conn.login(conn_info.user, conn_info.password)
        conn.select(conn_info.folder)

        status, data = conn.search(None, "UNSEEN")
        if status != "OK":
            return []

        emails: list[FetchedEmail] = []
        for uid in data[0].split():
            status, msg_data = conn.fetch(uid, "(BODY.PEEK[])")
            if status != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)
            body, content_type = _extract_body(msg)
            emails.append(FetchedEmail(uid=uid, subject=_decode_subject(msg), body=body, content_type=content_type))

        return emails
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _mark_processed_sync(conn_info: ImapConnectionInfo, uid: bytes) -> None:
    conn = imaplib.IMAP4_SSL(conn_info.host, conn_info.port)
    try:
        conn.login(conn_info.user, conn_info.password)
        conn.select(conn_info.folder)
        conn.store(uid, "+FLAGS", "\\Seen")
        conn.copy(uid, conn_info.processed_folder)
        conn.store(uid, "+FLAGS", "\\Deleted")
        conn.expunge()
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _mark_seen_sync(conn_info: ImapConnectionInfo, uid: bytes) -> None:
    conn = imaplib.IMAP4_SSL(conn_info.host, conn_info.port)
    try:
        conn.login(conn_info.user, conn_info.password)
        conn.select(conn_info.folder)
        conn.store(uid, "+FLAGS", "\\Seen")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def build_registry() -> ParserRegistry:
    return ParserRegistry([ReferenceBookingComParser()])


async def load_registry(db: AsyncSession) -> ParserRegistry:
    registry = build_registry()
    result = await db.execute(
        select(ParserFieldMapping)
        .options(selectinload(ParserFieldMapping.fields))
        .where(ParserFieldMapping.is_active.is_(True))
    )
    for mapping in result.scalars().all():
        registry.register(GenericFieldMappingParser(mapping))
    return registry


async def create_reservation_from_parsed(
    db: AsyncSession, parsed: ParsedReservation, parser_slug: str, raw_body: str
) -> Reservation:
    """Builds and persists a Reservation (+ room lines, + auto room
    assignment if enabled) from a successfully parsed email. Shared by
    live ingestion and by the "reparse" admin action so both paths stay
    in sync."""
    reservation = Reservation(
        **parsed.model_dump(exclude={"extra_fields", "room_lines"}),
        parser_slug=parser_slug,
        raw_source_text=raw_body,
        extra_fields=parsed.extra_fields or None,
        status=ReservationStatus.confirmed,
    )
    for index, room_line in enumerate(parsed.room_lines):
        reservation.room_lines.append(
            ReservationRoomLine(
                sort_order=index,
                room_type=room_line.room_type,
                nights=room_line.nights,
                price_per_night=room_line.price_per_night,
                price_total=room_line.price_total,
            )
        )
    db.add(reservation)
    await db.flush()
    app_settings = await get_or_create_settings(db)
    if app_settings.room_auto_assign_enabled:
        await assign_rooms_for_reservation(db, reservation)
    return reservation


async def apply_cancellation_email(
    db: AsyncSession, parser: GenericFieldMappingParser, subject: str, body: str, content_type: str
) -> Reservation:
    """For a `kind="cancellation"` parser match: extracts the
    reservation reference and marks the existing Reservation cancelled
    instead of creating a new one — an OTA "booking cancelled" notice
    often reuses a template very similar to the original confirmation
    email, so treating every match as a new booking would silently
    create a duplicate reservation instead of cancelling the real one.
    Raises ParserError (handled the same way as any other parse
    failure — left as an unparsed email for manual follow-up) if the
    reference can't be extracted or doesn't match any known
    reservation."""
    external_ref = parser.extract_cancellation_ref(body, content_type)
    reservation = (
        await db.execute(
            select(Reservation)
            .where(Reservation.external_ref == external_ref, Reservation.status != ReservationStatus.cancelled)
            .order_by(Reservation.created_at.desc())
        )
    ).scalars().first()
    if reservation is None:
        raise ParserError(f"cancellation email for unknown reservation ref {external_ref!r}")
    reservation.status = ReservationStatus.cancelled
    return reservation


async def _record_unparsed(
    db: AsyncSession, fetched: FetchedEmail, reason: str, parser_slug: str | None
) -> UnparsedEmail:
    """Persists the raw subject/body of an email no parser could
    handle, so an operator can fix/add a parser mapping later and
    reparse this exact email from the admin UI's "Unparsed emails"
    page instead of waiting for it to be resent."""
    unparsed = UnparsedEmail(
        subject=fetched.subject,
        body=fetched.body,
        content_type=fetched.content_type,
        reason=reason,
        parser_slug=parser_slug,
    )
    db.add(unparsed)
    await db.flush()
    await audit.log(
        db,
        actor="system",
        action="email.unparsed",
        entity_type="unparsed_email",
        entity_id=unparsed.id,
        detail={"subject": fetched.subject, "parser_slug": parser_slug, "reason": reason},
    )
    return unparsed


async def _process_email(
    db: AsyncSession, registry: ParserRegistry, fetched: FetchedEmail, conn_info: ImapConnectionInfo
) -> None:
    parser = registry.find(fetched.subject, fetched.body, fetched.content_type)

    if parser is None:
        await _record_unparsed(db, fetched, reason="no matching parser", parser_slug=None)
        await db.commit()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _mark_seen_sync, conn_info, fetched.uid)
        return

    is_cancellation = getattr(parser, "kind", "reservation") == "cancellation"

    try:
        if is_cancellation:
            reservation = await apply_cancellation_email(
                db, parser, fetched.subject, fetched.body, fetched.content_type
            )
        else:
            parsed = parser.parse(fetched.subject, fetched.body, fetched.content_type)
            reservation = await create_reservation_from_parsed(db, parsed, parser.slug, fetched.body)
    except ParserError as exc:
        await _record_unparsed(db, fetched, reason=str(exc), parser_slug=parser.slug)
        await db.commit()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _mark_seen_sync, conn_info, fetched.uid)
        return

    await audit.log(
        db,
        actor="system",
        action="reservation.cancelled_by_email" if is_cancellation else "reservation.ingested",
        entity_type="reservation",
        entity_id=reservation.id,
        detail={"parser_slug": parser.slug, "subject": fetched.subject},
    )
    await db.commit()

    if not is_cancellation:
        await maybe_auto_print(db, reservation)

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _mark_processed_sync, conn_info, fetched.uid)


async def maybe_auto_print(db: AsyncSession, reservation: Reservation) -> None:
    """If enabled in Settings, print a newly-ingested reservation to
    the configured default station automatically — no "Print now"
    click needed. Printing failures are logged but never block
    ingestion; the reservation stays available for a manual print."""
    app_settings = await get_or_create_settings(db)
    if not app_settings.auto_print_enabled or app_settings.auto_print_station_id is None:
        return

    station = await db.get(PrintStation, app_settings.auto_print_station_id)
    if station is None or not station.is_active:
        await audit.log(
            db,
            actor="system",
            action="print_job.auto_print_skipped",
            entity_type="reservation",
            entity_id=reservation.id,
            detail={"reason": "auto-print station missing or inactive"},
        )
        await db.commit()
        return

    try:
        # room_lines/assigned_room may never have been touched in-memory
        # (e.g. the parser produced no room lines, or assignment found no
        # free room) — explicitly (and async-safely) load them before the
        # sync build_reservation_receipt call accesses them, otherwise
        # SQLAlchemy attempts a lazy load outside of a greenlet context
        # and crashes.
        reservation = (
            await db.execute(
                select(Reservation)
                .options(
                    selectinload(Reservation.room_lines).selectinload(ReservationRoomLine.assigned_room),
                    selectinload(Reservation.assigned_room),
                )
                .where(Reservation.id == reservation.id)
            )
        ).scalar_one()
        text_summary, escpos_bytes = printing.build_reservation_receipt(reservation, station, app_settings)
        job = await printing.enqueue_print_job(
            db,
            station=station,
            reservation=reservation,
            payload_text=text_summary,
            escpos_bytes=escpos_bytes,
            requested_by="system (auto-print)",
        )
        await audit.log(
            db,
            actor="system",
            action="print_job.auto_printed",
            entity_type="print_job",
            entity_id=job.id,
            detail={"reservation_id": reservation.id, "station_id": station.id},
        )
        await db.commit()
    except Exception:
        logger.exception("auto-print failed for reservation id=%s", reservation.id)


async def poll_once() -> int:
    async with async_session_maker() as db:
        conn_info = await load_imap_connection_info(db)
        if conn_info is None:
            return 0

        loop = asyncio.get_running_loop()
        emails = await loop.run_in_executor(None, _fetch_unseen_sync, conn_info)
        if not emails:
            return 0

        registry = await load_registry(db)
        for fetched in emails:
            try:
                await _process_email(db, registry, fetched, conn_info)
            except Exception:
                logger.exception("failed to process email uid=%s", fetched.uid)

        return len(emails)


async def _current_poll_interval_seconds() -> int:
    async with async_session_maker() as db:
        row = await get_or_create_settings(db)
        return row.imap_poll_seconds or DEFAULT_POLL_SECONDS


async def email_poll_loop() -> None:
    while True:
        try:
            count = await poll_once()
            if count:
                logger.info("processed %d email(s)", count)
        except Exception:
            logger.exception("email poll iteration failed")

        try:
            interval = await _current_poll_interval_seconds()
        except Exception:
            logger.exception("failed to read poll interval, falling back to default")
            interval = DEFAULT_POLL_SECONDS

        await asyncio.sleep(interval)
