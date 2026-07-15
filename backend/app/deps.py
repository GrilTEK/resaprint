from datetime import datetime, timezone

from fastapi import Cookie, Depends, Header, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.exceptions import ForbiddenHtml, NotAuthenticatedHtml
from app.models.admin_pin import AdminPin, AdminRole
from app.models.print_station import PrintStation, StationConnectionType
from app.services.auth_service import SESSION_COOKIE_NAME, read_session_token

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

__all__ = [
    "get_db",
    "require_admin_session",
    "require_admin_session_html",
    "require_admin_role",
    "require_admin_role_html",
    "require_station_key",
]


async def require_admin_session(
    db: AsyncSession = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AdminPin:
    if session_cookie is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    admin_pin_id = read_session_token(session_cookie)
    if admin_pin_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired session")

    result = await db.execute(
        select(AdminPin).where(AdminPin.id == admin_pin_id, AdminPin.is_active.is_(True))
    )
    admin_pin = result.scalar_one_or_none()
    if admin_pin is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="session no longer valid")
    return admin_pin


async def require_admin_session_html(
    db: AsyncSession = Depends(get_db),
    session_cookie: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> AdminPin:
    """Same as require_admin_session but raises NotAuthenticatedHtml,
    which main.py's exception handler turns into a redirect to /login
    instead of a 401 JSON body — appropriate for server-rendered pages."""
    if session_cookie is None:
        raise NotAuthenticatedHtml()

    admin_pin_id = read_session_token(session_cookie)
    if admin_pin_id is None:
        raise NotAuthenticatedHtml()

    result = await db.execute(
        select(AdminPin).where(AdminPin.id == admin_pin_id, AdminPin.is_active.is_(True))
    )
    admin_pin = result.scalar_one_or_none()
    if admin_pin is None:
        raise NotAuthenticatedHtml()
    return admin_pin


async def require_admin_role(admin: AdminPin = Depends(require_admin_session)) -> AdminPin:
    """Admin-only JSON routes (settings, parsers, stations, users, rooms)."""
    if admin.role != AdminRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin role required")
    return admin


async def require_admin_role_html(admin: AdminPin = Depends(require_admin_session_html)) -> AdminPin:
    """Same as require_admin_role but for HTML pages — redirects a
    reception-role user back to the dashboard instead of a raw 403."""
    if admin.role != AdminRole.admin:
        raise ForbiddenHtml()
    return admin


async def require_station_key(
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> PrintStation:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing station API key")

    api_key = authorization.split(" ", 1)[1].strip()
    if len(api_key) < 12:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")

    prefix = api_key[:12]
    result = await db.execute(
        select(PrintStation).where(
            PrintStation.api_key_prefix == prefix,
            PrintStation.connection_type == StationConnectionType.usb_agent,
            PrintStation.is_active.is_(True),
        )
    )
    station = result.scalar_one_or_none()
    if station is None or not station.api_key_hash or not _pwd_context.verify(api_key, station.api_key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid API key")

    station.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    return station
