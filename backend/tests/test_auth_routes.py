"""HTTP-level tests for /login and /logout.

These specifically cover the HX-Request (HTMX) code path, not just the
plain-JSON path — a real bug shipped where the HTMX branch returned a
brand new HTMLResponse instead of the injected `response` object it
had called `.set_cookie()` on, so FastAPI silently dropped the cookie
and login appeared to "succeed" (200) while never actually
authenticating. The JSON-only unit tests in test_auth.py didn't catch
this because returning a plain pydantic model (not a Response
subclass) does let FastAPI merge cookies set on the injected response.
"""
import pytest
from httpx import AsyncClient

from app.models.admin_pin import AdminPin
from app.services.auth_service import SESSION_COOKIE_NAME, hash_pin


async def _seed_pin(db_session, pin="1234", label="Front desk"):
    db_session.add(AdminPin(label=label, pin_hash=hash_pin(pin)))
    await db_session.commit()


@pytest.mark.asyncio
async def test_htmx_login_sets_session_cookie(client: AsyncClient, db_session):
    await _seed_pin(db_session, "1234")

    response = await client.post("/login", data={"pin": "1234"}, headers={"HX-Request": "true"})

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies


@pytest.mark.asyncio
async def test_json_login_sets_session_cookie(client: AsyncClient, db_session):
    await _seed_pin(db_session, "1234")

    response = await client.post("/login", data={"pin": "1234"})

    assert response.status_code == 200
    assert SESSION_COOKIE_NAME in response.cookies


@pytest.mark.asyncio
async def test_htmx_login_cookie_actually_authenticates_dashboard(client: AsyncClient, db_session):
    await _seed_pin(db_session, "1234")

    login_resp = await client.post("/login", data={"pin": "1234"}, headers={"HX-Request": "true"})
    assert SESSION_COOKIE_NAME in login_resp.cookies

    dashboard_resp = await client.get("/", follow_redirects=False)
    assert dashboard_resp.status_code == 200


@pytest.mark.asyncio
async def test_htmx_login_wrong_pin_does_not_set_cookie(client: AsyncClient, db_session):
    await _seed_pin(db_session, "1234")

    response = await client.post("/login", data={"pin": "9999"}, headers={"HX-Request": "true"})

    assert response.status_code == 200  # HTMX error fragment, not a raised HTTPException
    assert SESSION_COOKIE_NAME not in response.cookies
    assert "Invalid PIN" in response.text


@pytest.mark.asyncio
async def test_unauthenticated_dashboard_redirects_to_login(client: AsyncClient):
    response = await client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_logout_clears_session_cookie(client: AsyncClient, db_session):
    await _seed_pin(db_session, "1234")
    await client.post("/login", data={"pin": "1234"}, headers={"HX-Request": "true"})

    logout_resp = await client.post("/logout", follow_redirects=False)
    assert logout_resp.status_code == 303

    # After logout, the dashboard must require login again.
    dashboard_resp = await client.get("/", follow_redirects=False)
    assert dashboard_resp.status_code == 303
    assert dashboard_resp.headers["location"] == "/login"
