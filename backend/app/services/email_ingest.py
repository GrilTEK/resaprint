"""IMAP reservation-email ingestion.

Uses stdlib `imaplib` (no third-party IMAP dependency — "boring
libraries"), run in a thread executor since imaplib is synchronous.
Polls a single configurable folder for UNSEEN messages, dispatches
each to the parser registry, and either creates a Reservation (moving
the message to the processed folder) or logs an `email.unparsed` audit
entry (leaving the message in place, marked \\Seen so it isn't
reprocessed every poll).
"""
from __future__ import annotations

import asyncio
import email
import imaplib
import logging
from dataclasses import dataclass
from email.message import Message

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_maker
from app.models.reservation import Reservation, ReservationStatus
from app.services import audit
from app.services.parser_registry import ParserError, ParserRegistry
from app.services.parsers.reference_booking_com import ReferenceBookingComParser

logger = logging.getLogger("resaprint.email_ingest")


@dataclass
class FetchedEmail:
    uid: bytes
    subject: str
    body: str
    content_type: str


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


def _fetch_unseen_sync() -> list[FetchedEmail]:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    try:
        conn.login(settings.imap_user, settings.imap_password)
        conn.select(settings.imap_folder)

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


def _mark_processed_sync(uid: bytes) -> None:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    try:
        conn.login(settings.imap_user, settings.imap_password)
        conn.select(settings.imap_folder)
        conn.store(uid, "+FLAGS", "\\Seen")
        conn.copy(uid, settings.imap_processed_folder)
        conn.store(uid, "+FLAGS", "\\Deleted")
        conn.expunge()
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _mark_seen_sync(uid: bytes) -> None:
    conn = imaplib.IMAP4_SSL(settings.imap_host, settings.imap_port)
    try:
        conn.login(settings.imap_user, settings.imap_password)
        conn.select(settings.imap_folder)
        conn.store(uid, "+FLAGS", "\\Seen")
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def build_registry() -> ParserRegistry:
    return ParserRegistry([ReferenceBookingComParser()])


async def load_registry(db: AsyncSession) -> ParserRegistry:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.parser_mapping import ParserFieldMapping
    from app.services.parser_registry import GenericFieldMappingParser

    registry = build_registry()
    result = await db.execute(
        select(ParserFieldMapping)
        .options(selectinload(ParserFieldMapping.fields))
        .where(ParserFieldMapping.is_active.is_(True))
    )
    for mapping in result.scalars().all():
        registry.register(GenericFieldMappingParser(mapping))
    return registry


async def _process_email(db: AsyncSession, registry: ParserRegistry, fetched: FetchedEmail) -> None:
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
        await loop.run_in_executor(None, _mark_seen_sync, fetched.uid)
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
        await loop.run_in_executor(None, _mark_seen_sync, fetched.uid)
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
    await loop.run_in_executor(None, _mark_processed_sync, fetched.uid)


async def poll_once() -> int:
    loop = asyncio.get_running_loop()
    emails = await loop.run_in_executor(None, _fetch_unseen_sync)
    if not emails:
        return 0

    async with async_session_maker() as db:
        registry = await load_registry(db)
        for fetched in emails:
            try:
                await _process_email(db, registry, fetched)
            except Exception:
                logger.exception("failed to process email uid=%s", fetched.uid)

    return len(emails)


async def email_poll_loop() -> None:
    while True:
        try:
            count = await poll_once()
            if count:
                logger.info("processed %d email(s)", count)
        except Exception:
            logger.exception("email poll iteration failed")
        await asyncio.sleep(settings.imap_poll_seconds)
