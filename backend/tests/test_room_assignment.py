import pytest
from httpx import AsyncClient

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
async def test_reservation_auto_assigned_to_matching_free_room(authed_client: AsyncClient):
    await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Double Room"})

    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    assert create_resp.status_code == 201
    assert create_resp.json()["assigned_room_id"] is not None


@pytest.mark.asyncio
async def test_no_room_of_matching_category_leaves_unassigned(authed_client: AsyncClient):
    await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Suite"})

    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    assert create_resp.status_code == 201
    assert create_resp.json()["assigned_room_id"] is None


@pytest.mark.asyncio
async def test_overlapping_stays_get_different_rooms_then_third_is_unassigned(authed_client: AsyncClient):
    await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Double Room"})
    await authed_client.post("/api/v1/rooms", json={"room_number": "102", "category": "Double Room"})

    first = (await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)).json()
    second = (await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)).json()
    third = (await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)).json()

    assert first["assigned_room_id"] is not None
    assert second["assigned_room_id"] is not None
    assert first["assigned_room_id"] != second["assigned_room_id"]
    assert third["assigned_room_id"] is None


@pytest.mark.asyncio
async def test_non_overlapping_stays_can_reuse_the_same_room(authed_client: AsyncClient):
    await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Double Room"})

    first = (await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)).json()

    later_payload = {**RESERVATION_PAYLOAD, "checkin": "2026-10-05", "checkout": "2026-10-07"}
    second = (await authed_client.post("/api/v1/reservations", json=later_payload)).json()

    assert first["assigned_room_id"] == second["assigned_room_id"]


@pytest.mark.asyncio
async def test_inactive_room_is_not_assigned(authed_client: AsyncClient):
    room_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Double Room"})
    room_id = room_resp.json()["id"]
    await authed_client.patch(f"/api/v1/rooms/{room_id}", json={"is_active": False})

    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    assert create_resp.json()["assigned_room_id"] is None


@pytest.mark.asyncio
async def test_reassign_room_action_finds_newly_added_room(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]
    assert create_resp.json()["assigned_room_id"] is None

    await authed_client.post("/api/v1/rooms", json={"room_number": "101", "category": "Double Room"})

    reassign_resp = await authed_client.post(f"/api/v1/reservations/{reservation_id}/reassign-room")
    assert reassign_resp.status_code == 200
    assert reassign_resp.json()["assigned_room_id"] is not None
