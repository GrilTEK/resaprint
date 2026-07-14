import email
from email.mime.text import MIMEText

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.reservation import Reservation
from app.services import email_ingest
from app.services.email_ingest import FetchedEmail, _decode_subject, _extract_body, _process_email
from app.services.parser_registry import ParserRegistry
from app.services.parsers.reference_booking_com import ReferenceBookingComParser


def test_decode_subject_plain_ascii():
    msg = MIMEText("body")
    msg["Subject"] = "Plain subject"
    assert _decode_subject(email.message_from_string(msg.as_string())) == "Plain subject"


def test_extract_body_plain_text():
    msg = MIMEText("hello world", "plain")
    body, content_type = _extract_body(email.message_from_string(msg.as_string()))
    assert body.strip() == "hello world"
    assert content_type == "text/plain"


MATCHING_SUBJECT = "New booking confirmation - Booking.com"
MATCHING_BODY = (
    "Guest name: Jane Doe\n"
    "Check-in: 15-08-2026\n"
    "Check-out: 18-08-2026\n"
    "Booking number: 987654\n"
    "Total price: EUR 200.00\n"
)


@pytest.mark.asyncio
async def test_process_email_creates_reservation_and_marks_processed(db_session: AsyncSession, monkeypatch):
    calls = []
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda uid: calls.append(("processed", uid)))
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda uid: calls.append(("seen", uid)))

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"1", subject=MATCHING_SUBJECT, body=MATCHING_BODY, content_type="text/plain")

    await _process_email(db_session, registry, fetched)

    result = await db_session.execute(select(Reservation))
    reservations = result.scalars().all()
    assert len(reservations) == 1
    assert reservations[0].guest_name == "Jane Doe"
    assert reservations[0].parser_slug == "booking_com_reference"
    assert calls == [("processed", b"1")]


@pytest.mark.asyncio
async def test_process_email_logs_unparsed_when_no_parser_matches(db_session: AsyncSession, monkeypatch):
    calls = []
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda uid: calls.append(("processed", uid)))
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda uid: calls.append(("seen", uid)))

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"2", subject="Unrelated newsletter", body="nothing useful here", content_type="text/plain")

    await _process_email(db_session, registry, fetched)

    result = await db_session.execute(select(Reservation))
    assert result.scalars().all() == []

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.unparsed"))
    entries = audit_result.scalars().all()
    assert len(entries) == 1
    assert entries[0].actor == "system"
    assert calls == [("seen", b"2")]


@pytest.mark.asyncio
async def test_process_email_logs_unparsed_when_required_field_missing(db_session: AsyncSession, monkeypatch):
    calls = []
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda uid: calls.append(("processed", uid)))
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda uid: calls.append(("seen", uid)))

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(
        uid=b"3", subject=MATCHING_SUBJECT, body="Guest name: Missing dates\n", content_type="text/plain"
    )

    await _process_email(db_session, registry, fetched)

    result = await db_session.execute(select(Reservation))
    assert result.scalars().all() == []
    assert calls == [("seen", b"3")]
