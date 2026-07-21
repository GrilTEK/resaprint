import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog
from app.models.parser_mapping import ParserFieldMapping
from app.models.reservation import Reservation

RESERVATION_PAYLOAD = {
    "guest_name": "Alice Example",
    "source_channel": "manual",
    "checkin": "2026-10-01",
    "checkout": "2026-10-03",
    "room_type": "Double Room",
    "price_total": "120.00",
    "price_currency": "EUR",
}


@pytest.mark.asyncio
async def test_create_parser_with_cancellation_kind(authed_client: AsyncClient, db_session: AsyncSession):
    response = await authed_client.post(
        "/parsers", data={"profile_slug": "cubilis_cancel", "match_subject_regex": "cancelled", "kind": "cancellation"}
    )
    assert response.status_code == 200
    mapping = (await db_session.execute(select(ParserFieldMapping))).scalars().one()
    assert mapping.kind.value == "cancellation"


@pytest.mark.asyncio
async def test_update_parser_kind_action(authed_client: AsyncClient, db_session: AsyncSession):
    await authed_client.post("/parsers", data={"profile_slug": "cubilis", "match_subject_regex": ""})
    mapping = (await db_session.execute(select(ParserFieldMapping))).scalars().one()
    assert mapping.kind.value == "reservation"

    response = await authed_client.post(f"/parsers/{mapping.id}/kind", data={"kind": "cancellation"})
    assert response.status_code == 200

    await db_session.refresh(mapping)
    assert mapping.kind.value == "cancellation"


@pytest.mark.asyncio
async def test_update_reservation_status_action(authed_client: AsyncClient, db_session: AsyncSession):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    response = await authed_client.post(f"/reservations/{reservation_id}/status", data={"status": "confirmed"})
    assert response.status_code == 200

    reservation = await db_session.get(Reservation, reservation_id)
    await db_session.refresh(reservation)
    assert reservation.status.value == "confirmed"

    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "reservation.status_changed"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_delete_reservation_requires_cancelled_status(authed_client: AsyncClient, db_session: AsyncSession):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    # Not cancelled yet — delete must be a no-op.
    response = await authed_client.post(f"/reservations/{reservation_id}/delete")
    assert response.status_code == 200
    assert await db_session.get(Reservation, reservation_id) is not None

    await authed_client.post(f"/reservations/{reservation_id}/status", data={"status": "cancelled"})
    delete_resp = await authed_client.post(f"/reservations/{reservation_id}/delete", follow_redirects=False)
    assert delete_resp.status_code == 303

    assert await db_session.get(Reservation, reservation_id) is None
    audit_result = await db_session.execute(select(AuditLog).where(AuditLog.action == "reservation.deleted"))
    assert len(audit_result.scalars().all()) == 1


@pytest.mark.asyncio
async def test_delete_reservation_requires_admin_role(reception_client: AsyncClient, db_session: AsyncSession):
    create_resp = await reception_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]
    await reception_client.post(f"/reservations/{reservation_id}/status", data={"status": "cancelled"})

    response = await reception_client.post(f"/reservations/{reservation_id}/delete", follow_redirects=False)
    assert response.status_code == 303

    assert await db_session.get(Reservation, reservation_id) is not None
