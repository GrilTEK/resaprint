"""Reception-role PINs get reservations/print-jobs but are locked out
of settings/parsers/stations/users/audit-log — both the JSON API and
the server-rendered HTML pages."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_reception_can_list_reservations(reception_client: AsyncClient):
    response = await reception_client.get("/api/v1/reservations")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_reception_can_list_print_jobs(reception_client: AsyncClient):
    response = await reception_client.get("/api/v1/print-jobs")
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/stations"),
        ("GET", "/api/v1/parsers"),
        ("GET", "/api/v1/config"),
        ("GET", "/api/v1/audit-log"),
        ("GET", "/api/v1/users"),
    ],
)
async def test_reception_gets_403_on_admin_only_json_routes(reception_client: AsyncClient, method, path):
    response = await reception_client.request(method, path)
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/stations", "/parsers", "/settings", "/audit-log", "/users"])
async def test_reception_redirected_away_from_admin_only_html_pages(reception_client: AsyncClient, path):
    response = await reception_client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/", "/reservations", "/print-jobs"])
async def test_reception_can_reach_non_admin_html_pages(reception_client: AsyncClient, path):
    response = await reception_client.get(path, follow_redirects=False)
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_admin_can_reach_admin_only_routes(authed_client: AsyncClient):
    response = await authed_client.get("/api/v1/stations")
    assert response.status_code == 200
    response = await authed_client.get("/stations", follow_redirects=False)
    assert response.status_code == 200
