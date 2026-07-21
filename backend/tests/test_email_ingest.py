import email
from datetime import date
from email.mime.text import MIMEText

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.parser_mapping import (
    ExtractionType,
    FieldTransform,
    ParserFieldMapping,
    ParserFieldMappingField,
    ParserMappingKind,
)
from app.models.print_job import PrintJob
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation, ReservationStatus
from app.models.unparsed_email import UnparsedEmail, UnparsedEmailStatus
from app.services import email_ingest
from app.services.app_settings import get_or_create_settings
from app.services.email_ingest import FetchedEmail, ImapConnectionInfo, _decode_subject, _extract_body, _process_email
from app.services.parser_registry import GenericFieldMappingParser, ParserRegistry
from app.services.parsers.reference_booking_com import ReferenceBookingComParser

TEST_CONN_INFO = ImapConnectionInfo(
    host="imap.example.com", port=993, user="user", password="pw", folder="INBOX", processed_folder="Processed"
)


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
    monkeypatch.setattr(
        email_ingest, "_mark_processed_sync", lambda conn, uid: calls.append(("processed", uid))
    )
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: calls.append(("seen", uid)))

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"1", subject=MATCHING_SUBJECT, body=MATCHING_BODY, content_type="text/plain")

    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    result = await db_session.execute(select(Reservation))
    reservations = result.scalars().all()
    assert len(reservations) == 1
    assert reservations[0].guest_name == "Jane Doe"
    assert reservations[0].parser_slug == "booking_com_reference"
    assert calls == [("processed", b"1")]


@pytest.mark.asyncio
async def test_process_email_logs_unparsed_when_no_parser_matches(db_session: AsyncSession, monkeypatch):
    calls = []
    monkeypatch.setattr(
        email_ingest, "_mark_processed_sync", lambda conn, uid: calls.append(("processed", uid))
    )
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: calls.append(("seen", uid)))

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"2", subject="Unrelated newsletter", body="nothing useful here", content_type="text/plain")

    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    result = await db_session.execute(select(Reservation))
    assert result.scalars().all() == []

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.unparsed"))
    entries = audit_result.scalars().all()
    assert len(entries) == 1
    assert entries[0].actor == "system"
    assert calls == [("seen", b"2")]

    unparsed_result = await db_session.execute(select(UnparsedEmail))
    unparsed = unparsed_result.scalars().one()
    assert unparsed.subject == "Unrelated newsletter"
    assert unparsed.body == "nothing useful here"
    assert unparsed.status == UnparsedEmailStatus.pending
    assert unparsed.parser_slug is None


@pytest.mark.asyncio
async def test_process_email_logs_unparsed_when_required_field_missing(db_session: AsyncSession, monkeypatch):
    calls = []
    monkeypatch.setattr(
        email_ingest, "_mark_processed_sync", lambda conn, uid: calls.append(("processed", uid))
    )
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: calls.append(("seen", uid)))

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(
        uid=b"3", subject=MATCHING_SUBJECT, body="Guest name: Missing dates\n", content_type="text/plain"
    )

    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    result = await db_session.execute(select(Reservation))
    assert result.scalars().all() == []
    assert calls == [("seen", b"3")]

    unparsed_result = await db_session.execute(select(UnparsedEmail))
    unparsed = unparsed_result.scalars().one()
    assert unparsed.parser_slug == "booking_com_reference"
    assert unparsed.status == UnparsedEmailStatus.pending


@pytest.mark.asyncio
async def test_process_email_auto_prints_when_enabled(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda conn, uid: None)
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: None)

    station = PrintStation(name="Front Desk", connection_type=StationConnectionType.usb_agent)
    db_session.add(station)
    await db_session.flush()

    app_settings = await get_or_create_settings(db_session)
    app_settings.auto_print_enabled = True
    app_settings.auto_print_station_id = station.id
    await db_session.commit()

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"10", subject=MATCHING_SUBJECT, body=MATCHING_BODY, content_type="text/plain")
    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    jobs = (await db_session.execute(select(PrintJob))).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].station_id == station.id
    assert jobs[0].requested_by == "system (auto-print)"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "print_job.auto_printed"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_process_email_does_not_auto_print_when_disabled(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda conn, uid: None)
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: None)

    station = PrintStation(name="Front Desk", connection_type=StationConnectionType.usb_agent)
    db_session.add(station)
    await db_session.flush()
    # auto_print_enabled left at its default (False) — station set but disabled.
    app_settings = await get_or_create_settings(db_session)
    app_settings.auto_print_station_id = station.id
    await db_session.commit()

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"11", subject=MATCHING_SUBJECT, body=MATCHING_BODY, content_type="text/plain")
    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    jobs = (await db_session.execute(select(PrintJob))).scalars().all()
    assert jobs == []


@pytest.mark.asyncio
async def test_process_email_auto_print_skips_when_station_inactive(db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda conn, uid: None)
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: None)

    station = PrintStation(name="Front Desk", connection_type=StationConnectionType.usb_agent, is_active=False)
    db_session.add(station)
    await db_session.flush()

    app_settings = await get_or_create_settings(db_session)
    app_settings.auto_print_enabled = True
    app_settings.auto_print_station_id = station.id
    await db_session.commit()

    registry = ParserRegistry([ReferenceBookingComParser()])
    fetched = FetchedEmail(uid=b"12", subject=MATCHING_SUBJECT, body=MATCHING_BODY, content_type="text/plain")
    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    jobs = (await db_session.execute(select(PrintJob))).scalars().all()
    assert jobs == []

    audit_result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "print_job.auto_print_skipped")
    )
    assert len(audit_result.scalars().all()) == 1

    # The reservation itself must still be created — a bad auto-print
    # config should never block ingestion.
    reservations = (await db_session.execute(select(Reservation))).scalars().all()
    assert len(reservations) == 1


async def _cancellation_mapping(db_session: AsyncSession) -> ParserFieldMapping:
    mapping = ParserFieldMapping(
        profile_slug="cubilis_cancellation",
        match_subject_regex="cancelled",
        kind=ParserMappingKind.cancellation,
    )
    db_session.add(mapping)
    await db_session.flush()
    db_session.add(
        ParserFieldMappingField(
            mapping_id=mapping.id, label="Reservation number", target_field="external_ref",
            extraction_type=ExtractionType.regex, pattern=r"Booking (\d+) cancelled", transform=FieldTransform.strip,
        )
    )
    await db_session.commit()
    await db_session.refresh(mapping, attribute_names=["fields"])
    return mapping


@pytest.mark.asyncio
async def test_process_cancellation_email_marks_existing_reservation_cancelled(
    db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda conn, uid: None)
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: None)

    reservation = Reservation(
        guest_name="Jane Doe", source_channel="cubilis", external_ref="60484374",
        checkin=date(2026, 8, 17), checkout=date(2026, 8, 21),
        status=ReservationStatus.confirmed,
    )
    db_session.add(reservation)
    await db_session.commit()

    mapping = await _cancellation_mapping(db_session)
    registry = ParserRegistry([GenericFieldMappingParser(mapping)])
    fetched = FetchedEmail(
        uid=b"20", subject="Booking 60484374 cancelled", body="Booking 60484374 cancelled", content_type="text/plain"
    )

    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    await db_session.refresh(reservation)
    assert reservation.status == ReservationStatus.cancelled

    reservations = (await db_session.execute(select(Reservation))).scalars().all()
    assert len(reservations) == 1, "a cancellation email must not create a duplicate reservation"

    audit_result = await db_session.execute(
        select(AuditLog).where(AuditLog.action == "reservation.cancelled_by_email")
    )
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_process_cancellation_email_for_unknown_ref_is_left_unparsed(
    db_session: AsyncSession, monkeypatch
):
    monkeypatch.setattr(email_ingest, "_mark_processed_sync", lambda conn, uid: None)
    monkeypatch.setattr(email_ingest, "_mark_seen_sync", lambda conn, uid: None)

    mapping = await _cancellation_mapping(db_session)
    registry = ParserRegistry([GenericFieldMappingParser(mapping)])
    fetched = FetchedEmail(
        uid=b"21", subject="Booking 99999999 cancelled", body="Booking 99999999 cancelled", content_type="text/plain"
    )

    await _process_email(db_session, registry, fetched, TEST_CONN_INFO)

    assert (await db_session.execute(select(Reservation))).scalars().all() == []
    unparsed = (await db_session.execute(select(UnparsedEmail))).scalars().one()
    assert "99999999" in unparsed.reason


@pytest.mark.asyncio
async def test_load_imap_connection_info_returns_none_when_unconfigured(db_session: AsyncSession):
    conn_info = await email_ingest.load_imap_connection_info(db_session)
    assert conn_info is None


@pytest.mark.asyncio
async def test_load_imap_connection_info_decrypts_password_from_db(db_session: AsyncSession):
    from app.services.app_settings import get_or_create_settings
    from app.services.crypto import encrypt

    row = await get_or_create_settings(db_session)
    row.imap_host = "imap.example.com"
    row.imap_user = "reservations@example.com"
    row.imap_password_encrypted = encrypt("s3cret")
    await db_session.commit()

    conn_info = await email_ingest.load_imap_connection_info(db_session)
    assert conn_info is not None
    assert conn_info.host == "imap.example.com"
    assert conn_info.password == "s3cret"
