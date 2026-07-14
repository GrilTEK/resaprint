import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_list_and_pair_station(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Reception USB", "connection_type": "usb_agent"}
    )
    assert create_resp.status_code == 201
    station = create_resp.json()
    assert station["api_key_prefix"] is None

    list_resp = await authed_client.get("/api/v1/stations")
    assert len(list_resp.json()) == 1

    pair_resp = await authed_client.post(f"/api/v1/stations/{station['id']}/pair")
    assert pair_resp.status_code == 200
    pair_body = pair_resp.json()
    assert pair_body["station_id"] == station["id"]
    assert len(pair_body["api_key"]) > 20

    status_resp = await authed_client.get(f"/api/v1/stations/{station['id']}/status")
    assert status_resp.json()["api_key_prefix"] == pair_body["api_key"][:12]


@pytest.mark.asyncio
async def test_delete_station_removes_it_entirely(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Reception USB", "connection_type": "usb_agent"}
    )
    station_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/stations/{station_id}/pair")

    delete_resp = await authed_client.delete(f"/api/v1/stations/{station_id}")
    assert delete_resp.status_code == 204

    get_resp = await authed_client.get(f"/api/v1/stations/{station_id}/status")
    assert get_resp.status_code == 404

    list_resp = await authed_client.get("/api/v1/stations")
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_delete_station_name_becomes_reusable(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Reception USB", "connection_type": "usb_agent"}
    )
    station_id = create_resp.json()["id"]

    await authed_client.delete(f"/api/v1/stations/{station_id}")

    recreate_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Reception USB", "connection_type": "usb_agent"}
    )
    assert recreate_resp.status_code == 201


@pytest.mark.asyncio
async def test_delete_station_cascades_print_jobs(authed_client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Reception USB", "connection_type": "usb_agent"}
    )
    station_id = create_resp.json()["id"]
    await authed_client.post("/api/v1/print-jobs", json={"station_id": station_id, "payload_text": "Hello"})

    delete_resp = await authed_client.delete(f"/api/v1/stations/{station_id}")
    assert delete_resp.status_code == 204

    jobs_resp = await authed_client.get("/api/v1/print-jobs")
    assert jobs_resp.json() == []


@pytest.mark.asyncio
async def test_paired_station_can_poll_and_ack_jobs(authed_client: AsyncClient, client: AsyncClient):
    create_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "Reception USB", "connection_type": "usb_agent"}
    )
    station_id = create_resp.json()["id"]
    pair_resp = await authed_client.post(f"/api/v1/stations/{station_id}/pair")
    api_key = pair_resp.json()["api_key"]

    manual_job_resp = await authed_client.post(
        "/api/v1/print-jobs", json={"station_id": station_id, "payload_text": "Test receipt"}
    )
    assert manual_job_resp.status_code == 201
    job_id = manual_job_resp.json()["id"]
    assert manual_job_resp.json()["status"] == "queued"

    headers = {"Authorization": f"Bearer {api_key}"}
    poll_resp = await client.get("/api/v1/print-jobs/poll", headers=headers)
    assert poll_resp.status_code == 200
    jobs = poll_resp.json()
    assert len(jobs) == 1
    assert jobs[0]["id"] == job_id
    assert jobs[0]["status"] == "sent"

    ack_resp = await client.post(f"/api/v1/print-jobs/{job_id}/ack", json={"status": "printed"}, headers=headers)
    assert ack_resp.status_code == 200
    assert ack_resp.json()["status"] == "printed"


@pytest.mark.asyncio
async def test_station_poll_rejects_missing_or_wrong_key(authed_client: AsyncClient, client: AsyncClient):
    no_auth_resp = await client.get("/api/v1/print-jobs/poll")
    assert no_auth_resp.status_code == 401

    wrong_key_resp = await client.get(
        "/api/v1/print-jobs/poll", headers={"Authorization": "Bearer not-a-real-key-at-all"}
    )
    assert wrong_key_resp.status_code == 401
