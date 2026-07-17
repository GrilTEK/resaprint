import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.parser_mapping import ExtractionType, FieldTransform, ParserFieldMapping, ParserFieldMappingField
from app.models.reservation import Reservation
from app.models.unparsed_email import UnparsedEmail, UnparsedEmailStatus

UNMATCHED_SUBJECT = "Reservation confirmed"
UNMATCHED_BODY = "Guest: Jane Doe\nCheckin: 2026-08-15\nCheckout: 2026-08-18\n"


async def _seed_unparsed(db_session: AsyncSession, **overrides) -> UnparsedEmail:
    unparsed = UnparsedEmail(
        subject=overrides.get("subject", UNMATCHED_SUBJECT),
        body=overrides.get("body", UNMATCHED_BODY),
        content_type=overrides.get("content_type", "text/plain"),
        reason=overrides.get("reason", "no matching parser"),
        parser_slug=overrides.get("parser_slug"),
    )
    db_session.add(unparsed)
    await db_session.commit()
    await db_session.refresh(unparsed)
    return unparsed


@pytest.mark.asyncio
async def test_unparsed_emails_page_requires_auth(client: AsyncClient):
    response = await client.get("/unparsed-emails", follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_unparsed_emails_page_lists_pending(authed_client: AsyncClient, db_session: AsyncSession):
    await _seed_unparsed(db_session)

    response = await authed_client.get("/unparsed-emails")
    assert response.status_code == 200
    assert UNMATCHED_SUBJECT in response.text


@pytest.mark.asyncio
async def test_reparse_with_no_matching_parser_stays_pending(authed_client: AsyncClient, db_session: AsyncSession):
    unparsed = await _seed_unparsed(db_session)

    response = await authed_client.post(f"/unparsed-emails/{unparsed.id}/reparse")
    assert response.status_code == 200

    await db_session.refresh(unparsed)
    assert unparsed.status == UnparsedEmailStatus.pending

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.reparse_failed"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_reparse_recovers_when_required_reservation_field_missing(
    authed_client: AsyncClient, db_session: AsyncSession
):
    """A mapping that matches the subject and extracts every mapped
    field can still fail at ParsedReservation.model_validate() if a
    field the schema requires (checkin/checkout) was never mapped at
    all — a plain pydantic ValidationError, not a ParserError. This
    must not 500 the reparse request either."""
    unparsed = await _seed_unparsed(db_session)

    mapping = ParserFieldMapping(profile_slug="generic_test", match_subject_regex="Reservation confirmed")
    db_session.add(mapping)
    await db_session.flush()
    db_session.add(
        ParserFieldMappingField(
            mapping_id=mapping.id, label="Guest", target_field="guest_name",
            extraction_type=ExtractionType.regex, pattern=r"Guest: (.+)", transform=FieldTransform.strip,
        )
    )
    await db_session.commit()

    response = await authed_client.post(f"/unparsed-emails/{unparsed.id}/reparse")
    assert response.status_code == 200

    await db_session.refresh(unparsed)
    assert unparsed.status == UnparsedEmailStatus.pending
    assert "unexpected error" in unparsed.reason

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.reparse_failed"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_reparse_after_adding_matching_parser_creates_reservation(
    authed_client: AsyncClient, db_session: AsyncSession
):
    unparsed = await _seed_unparsed(db_session)

    mapping = ParserFieldMapping(profile_slug="generic_test", match_subject_regex="Reservation confirmed")
    db_session.add(mapping)
    await db_session.flush()
    db_session.add_all(
        [
            ParserFieldMappingField(
                mapping_id=mapping.id, label="Guest", target_field="guest_name",
                extraction_type=ExtractionType.regex, pattern=r"Guest: (.+)", transform=FieldTransform.strip,
            ),
            ParserFieldMappingField(
                mapping_id=mapping.id, label="Checkin", target_field="checkin",
                extraction_type=ExtractionType.regex, pattern=r"Checkin: (.+)", transform=FieldTransform.parse_date_iso,
            ),
            ParserFieldMappingField(
                mapping_id=mapping.id, label="Checkout", target_field="checkout",
                extraction_type=ExtractionType.regex, pattern=r"Checkout: (.+)", transform=FieldTransform.parse_date_iso,
            ),
        ]
    )
    await db_session.commit()

    response = await authed_client.post(f"/unparsed-emails/{unparsed.id}/reparse")
    assert response.status_code == 200

    await db_session.refresh(unparsed)
    assert unparsed.status == UnparsedEmailStatus.resolved
    assert unparsed.resolved_reservation_id is not None

    reservation = await db_session.get(Reservation, unparsed.resolved_reservation_id)
    assert reservation.guest_name == "Jane Doe"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.reparsed"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_ignore_deletes_the_email(authed_client: AsyncClient, db_session: AsyncSession):
    unparsed = await _seed_unparsed(db_session)
    unparsed_id = unparsed.id

    response = await authed_client.post(f"/unparsed-emails/{unparsed_id}/ignore")
    assert response.status_code == 200
    assert UNMATCHED_SUBJECT not in response.text

    assert await db_session.get(UnparsedEmail, unparsed_id) is None

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.ignored"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_reparse_recovers_from_unexpected_exception(
    authed_client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """A failure that isn't a ParserError (e.g. a DB error while
    creating the reservation) must still leave the entry pending with a
    recorded reason, not 500 the request — reproduces the "Reparse
    button does nothing" symptom without a raw crash."""
    unparsed = await _seed_unparsed(db_session)

    mapping = ParserFieldMapping(profile_slug="generic_test", match_subject_regex="Reservation confirmed")
    db_session.add(mapping)
    await db_session.flush()
    db_session.add_all(
        [
            ParserFieldMappingField(
                mapping_id=mapping.id, label="Guest", target_field="guest_name",
                extraction_type=ExtractionType.regex, pattern=r"Guest: (.+)", transform=FieldTransform.strip,
            ),
            ParserFieldMappingField(
                mapping_id=mapping.id, label="Checkin", target_field="checkin",
                extraction_type=ExtractionType.regex, pattern=r"Checkin: (.+)", transform=FieldTransform.parse_date_iso,
            ),
            ParserFieldMappingField(
                mapping_id=mapping.id, label="Checkout", target_field="checkout",
                extraction_type=ExtractionType.regex, pattern=r"Checkout: (.+)", transform=FieldTransform.parse_date_iso,
            ),
        ]
    )
    await db_session.commit()

    from app.services import email_ingest

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(email_ingest, "create_reservation_from_parsed", _boom)

    response = await authed_client.post(f"/unparsed-emails/{unparsed.id}/reparse")
    assert response.status_code == 200

    await db_session.refresh(unparsed)
    assert unparsed.status == UnparsedEmailStatus.pending
    assert "simulated DB failure" in unparsed.reason

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "email.reparse_failed"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_reception_cannot_access_unparsed_emails(reception_client: AsyncClient):
    response = await reception_client.get("/unparsed-emails", follow_redirects=False)
    assert response.status_code == 303
