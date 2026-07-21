from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reservation import Reservation


@pytest.mark.asyncio
async def test_walkin_page_requires_auth(client: AsyncClient):
    response = await client.get("/reservations/walkin", follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_walkin_page_shows_message_when_no_rooms(authed_client: AsyncClient):
    response = await authed_client.get("/reservations/walkin")
    assert response.status_code == 200
    assert "Ni aktivnih sob" in response.text


@pytest.mark.asyncio
async def test_create_walkin_fills_in_defaults_and_generates_reference(
    authed_client: AsyncClient, db_session: AsyncSession
):
    room_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "205", "category": "Double"})
    room_id = room_resp.json()["id"]

    checkout = date.today() + timedelta(days=2)
    response = await authed_client.post(
        "/reservations/walkin",
        data={
            "guest_name": "Novak Novak",
            "checkout": checkout.isoformat(),
            "room_id": str(room_id),
            "price_total": "80.00",
            "guests_adults": "2",
            "guests_children": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    reservation = (await db_session.execute(select(Reservation))).scalars().one()
    assert reservation.guest_name == "Novak Novak"
    assert reservation.checkin == date.today()
    assert reservation.checkout == checkout
    assert reservation.assigned_room_id == room_id
    assert reservation.room_type == "Double"
    assert reservation.guests_adults == 2
    assert reservation.guests_children == 1
    assert reservation.price_currency == "EUR"
    assert reservation.source_channel == "01"
    assert reservation.status.value == "manual"

    today_prefix = date.today().strftime("%d%m%y")
    assert reservation.external_ref == f"{today_prefix}01"


@pytest.mark.asyncio
async def test_walkin_reference_sequence_increments_within_the_week(
    authed_client: AsyncClient, db_session: AsyncSession
):
    room_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "1", "category": "Single"})
    room_id = room_resp.json()["id"]
    checkout = (date.today() + timedelta(days=1)).isoformat()

    for i in range(3):
        resp = await authed_client.post(
            "/reservations/walkin",
            data={
                "guest_name": f"Guest {i}",
                "checkout": checkout,
                "room_id": str(room_id),
                "guests_adults": "1",
            },
        )
        assert resp.status_code == 303

    reservations = (
        (await db_session.execute(select(Reservation).order_by(Reservation.id))).scalars().all()
    )
    today_prefix = date.today().strftime("%d%m%y")
    assert [r.external_ref for r in reservations] == [
        f"{today_prefix}01", f"{today_prefix}02", f"{today_prefix}03"
    ]


@pytest.mark.asyncio
async def test_walkin_requires_room_selection(authed_client: AsyncClient):
    response = await authed_client.post(
        "/reservations/walkin",
        data={
            "guest_name": "No Room",
            "checkout": (date.today() + timedelta(days=1)).isoformat(),
            "guests_adults": "1",
        },
    )
    assert response.status_code == 422
