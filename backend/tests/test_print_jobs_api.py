import pytest
from httpx import AsyncClient

from app.services import printing


@pytest.mark.asyncio
async def test_manual_print_job_lan_success_marks_printed(authed_client: AsyncClient, monkeypatch):
    async def fake_send(host, port, payload, timeout=None):
        return None

    monkeypatch.setattr(printing, "send_lan_escpos", fake_send)

    station_resp = await authed_client.post(
        "/api/v1/stations",
        json={"name": "LAN Printer", "connection_type": "lan_escpos", "lan_host": "192.0.2.10", "lan_port": 9100},
    )
    station_id = station_resp.json()["id"]

    job_resp = await authed_client.post(
        "/api/v1/print-jobs", json={"station_id": station_id, "payload_text": "Hello"}
    )
    assert job_resp.status_code == 201
    assert job_resp.json()["status"] == "printed"


@pytest.mark.asyncio
async def test_manual_print_job_lan_failure_marks_failed_with_error(authed_client: AsyncClient, monkeypatch):
    async def fake_send_fail(host, port, payload, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(printing, "send_lan_escpos", fake_send_fail)

    station_resp = await authed_client.post(
        "/api/v1/stations",
        json={"name": "LAN Printer", "connection_type": "lan_escpos", "lan_host": "192.0.2.10", "lan_port": 9100},
    )
    station_id = station_resp.json()["id"]

    job_resp = await authed_client.post(
        "/api/v1/print-jobs", json={"station_id": station_id, "payload_text": "Hello"}
    )
    assert job_resp.status_code == 201
    body = job_resp.json()
    assert body["status"] == "failed"
    assert "connection refused" in body["last_error"]


@pytest.mark.asyncio
async def test_retry_print_job_resets_status_and_resends(authed_client: AsyncClient, monkeypatch):
    call_count = {"n": 0}

    async def fake_send(host, port, payload, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise OSError("printer offline")

    monkeypatch.setattr(printing, "send_lan_escpos", fake_send)

    station_resp = await authed_client.post(
        "/api/v1/stations",
        json={"name": "LAN Printer", "connection_type": "lan_escpos", "lan_host": "192.0.2.10", "lan_port": 9100},
    )
    station_id = station_resp.json()["id"]

    job_resp = await authed_client.post(
        "/api/v1/print-jobs", json={"station_id": station_id, "payload_text": "Hello"}
    )
    job_id = job_resp.json()["id"]
    assert job_resp.json()["status"] == "failed"

    retry_resp = await authed_client.post(f"/api/v1/print-jobs/{job_id}/retry")
    assert retry_resp.status_code == 200
    assert retry_resp.json()["status"] == "printed"
    assert retry_resp.json()["attempts"] == 2


@pytest.mark.asyncio
async def test_cancel_print_job(authed_client: AsyncClient):
    station_resp = await authed_client.post(
        "/api/v1/stations", json={"name": "USB station", "connection_type": "usb_agent"}
    )
    station_id = station_resp.json()["id"]

    job_resp = await authed_client.post(
        "/api/v1/print-jobs", json={"station_id": station_id, "payload_text": "Hello"}
    )
    job_id = job_resp.json()["id"]

    cancel_resp = await authed_client.post(f"/api/v1/print-jobs/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_list_print_jobs_filters_by_station(authed_client: AsyncClient):
    station_a = (
        await authed_client.post("/api/v1/stations", json={"name": "Station A", "connection_type": "usb_agent"})
    ).json()
    station_b = (
        await authed_client.post("/api/v1/stations", json={"name": "Station B", "connection_type": "usb_agent"})
    ).json()

    await authed_client.post("/api/v1/print-jobs", json={"station_id": station_a["id"], "payload_text": "A"})
    await authed_client.post("/api/v1/print-jobs", json={"station_id": station_b["id"], "payload_text": "B"})

    filtered = await authed_client.get("/api/v1/print-jobs", params={"station_id": station_a["id"]})
    assert len(filtered.json()) == 1
    assert filtered.json()[0]["station_id"] == station_a["id"]
