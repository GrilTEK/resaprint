import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_room_plan_requires_auth(client: AsyncClient):
    response = await client.get("/room-plan", follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_room_plan_maps_room_to_date_grid(authed_client: AsyncClient):
    room_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Double"})
    room_id = room_resp.json()["id"]

    create_resp = await authed_client.post(
        "/api/v1/reservations",
        json={
            "guest_name": "Grid Guest",
            "source_channel": "manual",
            "checkin": "2026-09-10",
            "checkout": "2026-09-13",
            "room_type": "Double",
            "price_total": "150.00",
            "price_currency": "EUR",
        },
    )
    reservation_id = create_resp.json()["id"]
    assign_resp = await authed_client.post(
        f"/api/v1/reservations/{reservation_id}/assign-room", json={"room_id": room_id}
    )
    assert assign_resp.status_code == 200

    response = await authed_client.get("/room-plan", params={"start": "2026-09-08", "days": 7})
    assert response.status_code == 200
    assert "101" in response.text
    assert "Grid Guest" in response.text
    assert f'href="/reservations/{reservation_id}"' in response.text


@pytest.mark.asyncio
async def test_room_plan_empty_when_no_rooms(authed_client: AsyncClient):
    response = await authed_client.get("/room-plan", params={"start": "2026-09-08", "days": 7})
    assert response.status_code == 200
    assert "Ni aktivnih sob" in response.text


@pytest.mark.asyncio
async def test_new_reservation_page_requires_auth(client: AsyncClient):
    response = await client.get("/reservations/new", follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_create_reservation_via_form_redirects_to_detail(authed_client: AsyncClient):
    response = await authed_client.post(
        "/reservations/new",
        data={
            "guest_name": "Form Guest",
            "source_channel": "manual",
            "checkin": "2026-09-01",
            "checkout": "2026-09-02",
            "room_type": "Single",
            "guests_adults": "1",
            "guests_children": "0",
            "price_total": "50.00",
            "price_currency": "EUR",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    detail_resp = await authed_client.get(response.headers["location"])
    assert detail_resp.status_code == 200
    assert "Form Guest" in detail_resp.text
    assert "manual" in detail_resp.text
