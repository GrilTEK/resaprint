from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.admin_pin import AdminPin
from app.services.auth_service import (
    attempt_login,
    hash_pin,
    issue_session_token,
    read_session_token,
    verify_pin,
)


def test_hash_pin_and_verify_roundtrip():
    hashed = hash_pin("1234")
    assert hashed != "1234"
    assert verify_pin("1234", hashed)
    assert not verify_pin("9999", hashed)


def test_session_token_roundtrip():
    token = issue_session_token(admin_pin_id=42)
    assert read_session_token(token) == 42


def test_session_token_rejects_tampered_value():
    token = issue_session_token(admin_pin_id=42)
    # Flip a character in the middle of the signature segment — flipping
    # the very last base64 char can occasionally decode to the same
    # bytes at a 6-bit boundary, so pick one guaranteed to matter.
    mid = len(token) // 2
    tampered = token[:mid] + ("a" if token[mid] != "a" else "b") + token[mid + 1 :]
    assert read_session_token(tampered) is None


@pytest.mark.asyncio
async def test_attempt_login_success(db_session: AsyncSession):
    pin_row = AdminPin(label="Front desk", pin_hash=hash_pin("4321"))
    db_session.add(pin_row)
    await db_session.commit()
    await db_session.refresh(pin_row)

    result = await attempt_login(db_session, "4321")
    assert result is not None
    assert result.label == "Front desk"
    assert result.failed_attempts == 0


@pytest.mark.asyncio
async def test_attempt_login_failure_increments_counter(db_session: AsyncSession):
    pin_row = AdminPin(label="Manager", pin_hash=hash_pin("0000"))
    db_session.add(pin_row)
    await db_session.commit()
    await db_session.refresh(pin_row)

    result = await attempt_login(db_session, "9999")
    assert result is None

    await db_session.refresh(pin_row)
    assert pin_row.failed_attempts == 1


@pytest.mark.asyncio
async def test_attempt_login_locks_out_after_threshold(db_session: AsyncSession):
    pin_row = AdminPin(label="Manager", pin_hash=hash_pin("0000"))
    db_session.add(pin_row)
    await db_session.commit()
    await db_session.refresh(pin_row)

    for _ in range(settings.pin_lockout_threshold):
        await attempt_login(db_session, "wrong")

    await db_session.refresh(pin_row)
    assert pin_row.locked_until is not None
    assert pin_row.locked_until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)

    # Even the correct PIN is rejected while locked.
    result = await attempt_login(db_session, "0000")
    assert result is None


@pytest.mark.asyncio
async def test_attempt_login_ignores_inactive_pin(db_session: AsyncSession):
    pin_row = AdminPin(label="Revoked", pin_hash=hash_pin("1111"), is_active=False)
    db_session.add(pin_row)
    await db_session.commit()

    result = await attempt_login(db_session, "1111")
    assert result is None


@pytest.mark.asyncio
async def test_attempt_login_allows_after_lockout_window_expires(db_session: AsyncSession):
    pin_row = AdminPin(
        label="Manager",
        pin_hash=hash_pin("0000"),
        locked_until=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(pin_row)
    await db_session.commit()

    result = await attempt_login(db_session, "0000")
    assert result is not None
