"""PIN-based admin auth: bcrypt hashing, signed session cookies, lockout.

Session cookie (not JWT) because the admin UI is server-rendered
Jinja2+HTMX, not a decoupled SPA — a stateless JWT would only add
revocation complexity here for no benefit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.admin_pin import AdminPin
from app.services import audit

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_serializer = URLSafeTimedSerializer(settings.secret_key, salt="resaprint-admin-session")

SESSION_COOKIE_NAME = "resaprint_session"


def hash_pin(pin: str) -> str:
    return _pwd_context.hash(pin)


def verify_pin(pin: str, pin_hash: str) -> bool:
    return _pwd_context.verify(pin, pin_hash)


def issue_session_token(admin_pin_id: int) -> str:
    return _serializer.dumps({"admin_pin_id": admin_pin_id})


def read_session_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age_seconds)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("admin_pin_id")


def _is_locked(pin_row: AdminPin) -> bool:
    if pin_row.locked_until is None:
        return False
    return pin_row.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)


async def attempt_login(db: AsyncSession, pin: str) -> AdminPin | None:
    """Try `pin` against every active admin PIN. Returns the matched row
    on success, or None (invalid/locked — deliberately indistinguishable
    to the caller to avoid a lockout oracle)."""
    result = await db.execute(select(AdminPin).where(AdminPin.is_active.is_(True)))
    candidates = result.scalars().all()

    for pin_row in candidates:
        if _is_locked(pin_row):
            continue
        if verify_pin(pin, pin_row.pin_hash):
            pin_row.failed_attempts = 0
            pin_row.locked_until = None
            pin_row.last_login_at = datetime.now(timezone.utc)
            await audit.log(db, actor=pin_row.label, action="pin.login_success")
            await db.commit()
            return pin_row

    # No match: penalize every unlocked active PIN a little to avoid
    # leaking which PIN (if any) was "close" — simplest safe approach
    # given PINs, not usernames, are the only login identifier.
    for pin_row in candidates:
        if _is_locked(pin_row):
            continue
        pin_row.failed_attempts += 1
        if pin_row.failed_attempts >= settings.pin_lockout_threshold:
            pin_row.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=settings.pin_lockout_minutes
            )
            pin_row.failed_attempts = 0
            await audit.log(db, actor=pin_row.label, action="pin.locked_out")

    await audit.log(db, actor="unknown", action="pin.login_failed")
    await db.commit()
    return None


async def get_admin_pin(db: AsyncSession, admin_pin_id: int) -> AdminPin | None:
    result = await db.execute(
        select(AdminPin).where(AdminPin.id == admin_pin_id, AdminPin.is_active.is_(True))
    )
    return result.scalar_one_or_none()
