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
async def test_sheet_page_requires_auth(client: AsyncClient):
    response = await client.get("/reservations/sheet", follow_redirects=False)
    assert response.status_code == 303


@pytest.mark.asyncio
async def test_sheet_page_lists_arrivals_for_date(authed_client: AsyncClient):
    await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)

    response = await authed_client.get("/reservations/sheet", params={"date": "2026-10-01"})
    assert response.status_code == 200
    assert "Alice Example" in response.text


@pytest.mark.asyncio
async def test_sheet_page_excludes_cancelled_reservations(authed_client: AsyncClient):
    """The arrivals sheet should only show confirmed arrivals — a
    cancelled reservation shouldn't need a room prepped or a receipt
    printed as part of the daily arrivals workflow. (It's still fully
    visible/printable from the reservations list and its own detail
    page — just not on this operational sheet.)"""
    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]
    await authed_client.delete(f"/api/v1/reservations/{reservation_id}")

    response = await authed_client.get("/reservations/sheet", params={"date": "2026-10-01"})
    assert response.status_code == 200
    assert "Alice Example" not in response.text
    assert "No arrivals" in response.text


@pytest.mark.asyncio
async def test_sheet_page_empty_for_other_date(authed_client: AsyncClient):
    await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)

    response = await authed_client.get("/reservations/sheet", params={"date": "2026-11-15"})
    assert response.status_code == 200
    assert "No arrivals" in response.text


@pytest.mark.asyncio
async def test_assign_and_print_action_assigns_room_and_enqueues_job(authed_client: AsyncClient):
    room_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "301", "category": "Double Room"})
    room_id = room_resp.json()["id"]
    station_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Front Desk", "connection_type": "usb_agent"}
    )
    station_id = station_resp.json()["id"]

    create_resp = await authed_client.post("/api/v1/reservations", json=RESERVATION_PAYLOAD)
    reservation_id = create_resp.json()["id"]

    response = await authed_client.post(
        f"/reservations/{reservation_id}/assign-and-print",
        data={
            "sheet_date": "2026-10-01",
            "room_id": str(room_id),
            "room_line_id": "",
            "station_id": str(station_id),
        },
    )
    assert response.status_code == 200

    get_resp = await authed_client.get(f"/api/v1/reservations/{reservation_id}")
    assert get_resp.json()["assigned_room_id"] == room_id

    jobs_resp = await authed_client.get("/api/v1/print-jobs")
    assert len(jobs_resp.json()) == 1
    assert jobs_resp.json()[0]["reservation_id"] == reservation_id


@pytest.mark.asyncio
async def test_reservations_search_page_filters(authed_client: AsyncClient):
    await authed_client.post("/api/v1/reservations", json={**RESERVATION_PAYLOAD, "guest_name": "Alice Example"})
    await authed_client.post("/api/v1/reservations", json={**RESERVATION_PAYLOAD, "guest_name": "Bob Builder"})

    response = await authed_client.get("/reservations", params={"q": "Bob"})
    assert response.status_code == 200
    assert "Bob Builder" in response.text
    assert "Alice Example" not in response.text


@pytest.mark.asyncio
async def test_reservations_page_filters_by_status(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/reservations", json={**RESERVATION_PAYLOAD, "guest_name": "Cancel Me"}
    )
    await authed_client.post("/api/v1/reservations", json={**RESERVATION_PAYLOAD, "guest_name": "Keep Me"})
    await authed_client.delete(f"/api/v1/reservations/{create_resp.json()['id']}")

    response = await authed_client.get("/reservations", params={"status": "cancelled"})
    assert response.status_code == 200
    assert "Cancel Me" in response.text
    assert "Keep Me" not in response.text


@pytest.mark.asyncio
async def test_reservations_page_filters_by_channel_and_checkin_range(authed_client: AsyncClient):
    await authed_client.post(
        "/api/v1/reservations",
        json={**RESERVATION_PAYLOAD, "guest_name": "Channel A", "source_channel": "booking_com"},
    )
    await authed_client.post(
        "/api/v1/reservations",
        json={**RESERVATION_PAYLOAD, "guest_name": "Channel B", "source_channel": "walkin"},
    )

    response = await authed_client.get("/reservations", params={"source_channel": "walkin"})
    assert response.status_code == 200
    assert "Channel B" in response.text
    assert "Channel A" not in response.text

    out_of_range = await authed_client.get(
        "/reservations", params={"checkin_from": "2026-11-01", "checkin_to": "2026-11-30"}
    )
    assert "Channel A" not in out_of_range.text
    assert "Channel B" not in out_of_range.text
