import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_users_requires_admin(client: AsyncClient):
    response = await client.get("/api/v1/users")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_reception_user(authed_client: AsyncClient):
    response = await authed_client.post(
        "/api/v1/users", json={"label": "Front desk", "pin": "4321", "role": "reception"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "Front desk"
    assert body["role"] == "reception"
    assert body["is_active"] is True
    assert "pin_hash" not in body
    assert "pin" not in body


@pytest.mark.asyncio
async def test_new_reception_user_can_actually_log_in(authed_client: AsyncClient, client: AsyncClient):
    await authed_client.post("/api/v1/users", json={"label": "Front desk", "pin": "4321", "role": "reception"})

    login_resp = await client.post("/login", data={"pin": "4321"})
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_update_user_role_and_rotate_pin(authed_client: AsyncClient, client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/users", json={"label": "Front desk", "pin": "4321", "role": "reception"}
    )
    user_id = create_resp.json()["id"]

    update_resp = await authed_client.patch(f"/api/v1/users/{user_id}", json={"pin": "9999"})
    assert update_resp.status_code == 200

    old_pin_login = await client.post("/login", data={"pin": "4321"})
    assert old_pin_login.status_code == 401

    new_client_login = await authed_client.post("/login", data={"pin": "9999"})
    assert new_client_login.status_code == 200


@pytest.mark.asyncio
async def test_delete_user(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/users", json={"label": "Front desk", "pin": "4321", "role": "reception"}
    )
    user_id = create_resp.json()["id"]

    delete_resp = await authed_client.delete(f"/api/v1/users/{user_id}")
    assert delete_resp.status_code == 204

    list_resp = await authed_client.get("/api/v1/users")
    assert all(u["id"] != user_id for u in list_resp.json())


@pytest.mark.asyncio
async def test_cannot_delete_last_active_admin(authed_client: AsyncClient):
    # authed_client's own PIN ("Test admin") is the only active admin.
    me_resp = await authed_client.get("/api/v1/users")
    admin_id = next(u["id"] for u in me_resp.json() if u["label"] == "Test admin")

    response = await authed_client.delete(f"/api/v1/users/{admin_id}")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cannot_demote_last_active_admin(authed_client: AsyncClient):
    me_resp = await authed_client.get("/api/v1/users")
    admin_id = next(u["id"] for u in me_resp.json() if u["label"] == "Test admin")

    response = await authed_client.patch(f"/api/v1/users/{admin_id}", json={"role": "reception"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_cannot_deactivate_last_active_admin(authed_client: AsyncClient):
    me_resp = await authed_client.get("/api/v1/users")
    admin_id = next(u["id"] for u in me_resp.json() if u["label"] == "Test admin")

    response = await authed_client.patch(f"/api/v1/users/{admin_id}", json={"is_active": False})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_can_delete_admin_when_another_admin_still_active(authed_client: AsyncClient):
    # "Test admin" (authed_client's own identity) is already one active
    # admin; adding a second means deleting either one individually is
    # fine as long as at least one remains.
    create_resp = await authed_client.post(
        "/api/v1/users", json={"label": "Second Admin", "pin": "1111", "role": "admin"}
    )
    second_admin_id = create_resp.json()["id"]

    response = await authed_client.delete(f"/api/v1/users/{second_admin_id}")
    assert response.status_code == 204
