import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rooms_requires_auth(client: AsyncClient):
    response = await client.get("/api/v1/rooms")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_reception_cannot_manage_rooms(reception_client: AsyncClient):
    response = await reception_client.get("/api/v1/rooms")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_and_list_room(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/rooms", json={"room_number": "101", "category": "Double Room", "floor": "1"}
    )
    assert create_resp.status_code == 201
    room = create_resp.json()
    assert room["room_number"] == "101"
    assert room["is_active"] is True

    list_resp = await authed_client.get("/api/v1/rooms")
    assert list_resp.status_code == 200
    assert any(r["room_number"] == "101" for r in list_resp.json())


@pytest.mark.asyncio
async def test_update_room(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "102", "category": "Single"})
    room_id = create_resp.json()["id"]

    update_resp = await authed_client.patch(f"/api/v1/rooms/{room_id}", json={"is_active": False})
    assert update_resp.status_code == 200
    assert update_resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_delete_room(authed_client: AsyncClient):
    create_resp = await authed_client.post("/api/v1/rooms", json={"room_number": "103", "category": "Single"})
    room_id = create_resp.json()["id"]

    delete_resp = await authed_client.delete(f"/api/v1/rooms/{room_id}")
    assert delete_resp.status_code == 204

    list_resp = await authed_client.get("/api/v1/rooms")
    assert all(r["id"] != room_id for r in list_resp.json())
