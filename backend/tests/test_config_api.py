import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_config_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/config")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_config_seeds_defaults_on_first_access(authed_client: AsyncClient):
    response = await authed_client.get("/api/v1/config")
    assert response.status_code == 200
    body = response.json()
    assert body["imap_folder"] == "INBOX"
    assert body["imap_has_password"] is False
    assert body["auto_print_enabled"] is False
    assert body["auto_print_station_id"] is None
    assert body["room_auto_assign_enabled"] is False
    assert body["receipt_font"] == "font_a"
    assert body["receipt_font_size"] == "normal"
    assert body["receipt_show_nights"] is True
    assert body["receipt_show_guests"] is True
    assert body["receipt_show_channel"] is True
    assert body["receipt_bold_labels"] is False


@pytest.mark.asyncio
async def test_patch_config_updates_receipt_layout(authed_client: AsyncClient):
    response = await authed_client.patch(
        "/api/v1/config",
        json={
            "receipt_font": "font_b",
            "receipt_font_size": "large",
            "receipt_bold_labels": True,
            "receipt_show_nights": False,
            "receipt_show_guests": False,
            "receipt_show_channel": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["receipt_font"] == "font_b"
    assert body["receipt_font_size"] == "large"
    assert body["receipt_bold_labels"] is True
    assert body["receipt_show_nights"] is False
    assert body["receipt_show_guests"] is False
    assert body["receipt_show_channel"] is False


@pytest.mark.asyncio
async def test_patch_config_sets_auto_print_station(authed_client: AsyncClient):
    station_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Front Desk", "connection_type": "usb_agent"}
    )
    station_id = station_resp.json()["id"]

    response = await authed_client.patch(
        "/api/v1/config", json={"auto_print_enabled": True, "auto_print_station_id": station_id}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["auto_print_enabled"] is True
    assert body["auto_print_station_id"] == station_id


@pytest.mark.asyncio
async def test_patch_config_can_disable_auto_print(authed_client: AsyncClient):
    station_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Front Desk", "connection_type": "usb_agent"}
    )
    station_id = station_resp.json()["id"]
    await authed_client.patch(
        "/api/v1/config", json={"auto_print_enabled": True, "auto_print_station_id": station_id}
    )

    response = await authed_client.patch("/api/v1/config", json={"auto_print_enabled": False})
    assert response.status_code == 200
    assert response.json()["auto_print_enabled"] is False


@pytest.mark.asyncio
async def test_patch_config_updates_fields(authed_client: AsyncClient):
    response = await authed_client.patch(
        "/api/v1/config",
        json={
            "imap_host": "imap.example.com",
            "imap_user": "reservations@example.com",
            "imap_password": "s3cret",
            "imap_folder": "Reservations",
            "imap_poll_seconds": 120,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["imap_host"] == "imap.example.com"
    assert body["imap_user"] == "reservations@example.com"
    assert body["imap_folder"] == "Reservations"
    assert body["imap_poll_seconds"] == 120
    assert body["imap_has_password"] is True

    # The password itself is never returned by the API.
    assert "imap_password" not in body
    assert "imap_password_encrypted" not in body


@pytest.mark.asyncio
async def test_patch_config_blank_password_leaves_existing_password_untouched(authed_client: AsyncClient):
    await authed_client.patch("/api/v1/config", json={"imap_password": "first-secret"})

    response = await authed_client.patch("/api/v1/config", json={"imap_host": "new-host.example.com"})
    assert response.status_code == 200
    assert response.json()["imap_has_password"] is True
    assert response.json()["imap_host"] == "new-host.example.com"


@pytest.mark.asyncio
async def test_patch_config_partial_update_preserves_other_fields(authed_client: AsyncClient):
    await authed_client.patch(
        "/api/v1/config", json={"imap_host": "imap.example.com", "imap_folder": "Reservations"}
    )

    response = await authed_client.patch("/api/v1/config", json={"imap_poll_seconds": 30})
    assert response.status_code == 200
    body = response.json()
    assert body["imap_poll_seconds"] == 30
    assert body["imap_host"] == "imap.example.com"
    assert body["imap_folder"] == "Reservations"
