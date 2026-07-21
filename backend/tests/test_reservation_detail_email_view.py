from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation


async def _seed_reservation(db_session: AsyncSession, raw_source_text: str | None) -> Reservation:
    reservation = Reservation(
        guest_name="Jane Doe",
        source_channel="manual",
        checkin=date(2026, 9, 1),
        checkout=date(2026, 9, 2),
        raw_source_text=raw_source_text,
    )
    db_session.add(reservation)
    await db_session.commit()
    await db_session.refresh(reservation)
    return reservation


@pytest.mark.asyncio
async def test_html_email_source_renders_in_sandboxed_iframe_with_raw_toggle(
    authed_client: AsyncClient, db_session: AsyncSession
):
    html_body = "<!DOCTYPE html><html><body><p>Reservation number: 123</p></body></html>"
    reservation = await _seed_reservation(db_session, html_body)

    response = await authed_client.get(f"/reservations/{reservation.id}")
    assert response.status_code == 200
    assert "<iframe" in response.text
    assert 'sandbox=""' in response.text
    assert "View raw" in response.text
    assert "View rendered" in response.text


@pytest.mark.asyncio
async def test_plain_text_email_source_renders_as_pre_without_iframe(
    authed_client: AsyncClient, db_session: AsyncSession
):
    reservation = await _seed_reservation(db_session, "Guest: Jane Doe\nCheckin: 2026-09-01\n")

    response = await authed_client.get(f"/reservations/{reservation.id}")
    assert response.status_code == 200
    assert "<iframe" not in response.text
    assert "Guest: Jane Doe" in response.text


@pytest.mark.asyncio
async def test_manually_created_reservation_shows_no_source_message(
    authed_client: AsyncClient, db_session: AsyncSession
):
    reservation = await _seed_reservation(db_session, None)

    response = await authed_client.get(f"/reservations/{reservation.id}")
    assert response.status_code == 200
    assert "none — manually created" in response.text
