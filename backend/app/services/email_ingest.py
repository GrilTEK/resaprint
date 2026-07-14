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
from app.models.reservation import Reservation, ReservationStatus
from app.services import audit
from app.services.app_settings import get_or_create_settings
from app.services.crypto import decrypt
from app.services.parser_registry import GenericFieldMappingParser, ParserError, ParserRegistry
from app.services.parsers.reference_booking_com import ReferenceBookingComParser

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


async def _process_email(
    db: AsyncSession, registry: ParserRegistry, fetched: FetchedEmail, conn_info: ImapConnectionInfo
) -> None:
    parser = registry.find(fetched.subject, fetched.body, fetched.content_type)

    if parser is None:
        await audit.log(
            db,
            actor="system",
            action="email.unparsed",
            detail={"subject": fetched.subject, "reason": "no matching parser"},
        )
        await db.commit()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _mark_seen_sync, conn_info, fetched.uid)
        return

    try:
        parsed = parser.parse(fetched.subject, fetched.body, fetched.content_type)
    except ParserError as exc:
        await audit.log(
            db,
            actor="system",
            action="email.unparsed",
            detail={"subject": fetched.subject, "parser_slug": parser.slug, "reason": str(exc)},
        )
        await db.commit()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _mark_seen_sync, conn_info, fetched.uid)
        return

    reservation = Reservation(
        **parsed.model_dump(exclude={"extra_fields"}),
        parser_slug=parser.slug,
        raw_source_text=fetched.body,
        extra_fields=parsed.extra_fields or None,
        status=ReservationStatus.confirmed,
    )
    db.add(reservation)
    await db.flush()
    await audit.log(
        db,
        actor="system",
        action="reservation.ingested",
        entity_type="reservation",
        entity_id=reservation.id,
        detail={"parser_slug": parser.slug, "subject": fetched.subject},
    )
    await db.commit()

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _mark_processed_sync, conn_info, fetched.uid)


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
