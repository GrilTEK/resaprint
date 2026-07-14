import pytest
from httpx import AsyncClient

RESERVATION_PAYLOAD = {
    "guest_name": "Alice Example",
    "source_channel": "manual",
    "checkin": "2026-10-01",
    "checkout": "2026-10-03",
    "room_type": "Single",
    "price_total": "120.00",
    "price_currency": "EUR",
}


@pytest.mark.asyncio
async def test_reservations_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/reservations")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_and_get_reservation(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    assert create_resp.status_code == 201
    reservation = create_resp.json()
    assert reservation["guest_name"] == "Alice Example"
    assert reservation["status"] == "manual"

    get_resp = await authed_client.get(f"/api/v1/reservations/{reservation['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == reservation["id"]


@pytest.mark.asyncio
async def test_list_reservations_filters_by_status(authed_client: AsyncClient):
    await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)

    list_resp = await authed_client.get("/api/v1/reservations", params={"status_filter": "manual"})
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1

    empty_resp = await authed_client.get("/api/v1/reservations", params={"status_filter": "cancelled"})
    assert empty_resp.json() == []


@pytest.mark.asyncio
async def test_update_reservation_applies_partial_fields(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    patch_resp = await authed_client.patch(
        f"/api/v1/reservations/{reservation_id}", json={"guest_name": "Alice Updated"}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["guest_name"] == "Alice Updated"
    assert patch_resp.json()["room_type"] == "Single"  # untouched field preserved


@pytest.mark.asyncio
async def test_cancel_reservation_sets_status(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    delete_resp = await authed_client.delete(f"/api/v1/reservations/{reservation_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_get_missing_reservation_404s(authed_client: AsyncClient):
    response = await authed_client.get("/api/v1/reservations/999999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_print_reservation_enqueues_job_for_usb_station(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    station_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Front Desk USB", "connection_type": "usb_agent"}
    )
    station_id = station_resp.json()["id"]

    print_resp = await authed_client.post(
        f"/api/v1/reservations/{reservation_id}/print", json={"station_id": station_id}
    )
    assert print_resp.status_code == 200
    body = print_resp.json()
    assert body["status"] == "queued"

    jobs_resp = await authed_client.get("/api/v1/print-jobs")
    assert len(jobs_resp.json()) == 1
    assert jobs_resp.json()[0]["reservation_id"] == reservation_id


@pytest.mark.asyncio
async def test_print_reservation_with_unknown_station_404s(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    print_resp = await authed_client.post(
        f"/api/v1/reservations/{reservation_id}/print", json={"station_id": 999999}
    )
    assert print_resp.status_code == 404
