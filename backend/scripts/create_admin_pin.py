"""Create (or replace) an admin PIN directly via SQLAlchemy.

Bypasses any shell/psql relay entirely, so there's no risk of `$`
characters in the bcrypt hash being mangled by shell quoting (a real
issue when hashing and inserting were two separate manual steps piped
through bash -c "..." double quotes).

Usage (from inside the api container, e.g. `docker compose exec api ...`):

    python scripts/create_admin_pin.py --label "Recepcija" --pin 1234
    python scripts/create_admin_pin.py --label "Recepcija"   # prompts for PIN, hidden input

If a PIN with the same label already exists, it is updated in place
(new hash, reactivated, lockout cleared) rather than duplicated.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys

sys.path.insert(0, "/app")  # noqa: E402 — running as a plain script inside the container

from sqlalchemy import select  # noqa: E402

from app.db import async_session_maker  # noqa: E402
from app.models.admin_pin import AdminPin  # noqa: E402
from app.services.auth_service import hash_pin  # noqa: E402


async def create_or_update_pin(label: str, pin: str) -> None:
    async with async_session_maker() as db:
        result = await db.execute(select(AdminPin).where(AdminPin.label == label))
        existing = result.scalar_one_or_none()

        if existing:
            existing.pin_hash = hash_pin(pin)
            existing.is_active = True
            existing.failed_attempts = 0
            existing.locked_until = None
            action = "Updated"
        else:
            db.add(AdminPin(label=label, pin_hash=hash_pin(pin)))
            action = "Created"

        await db.commit()

    print(f"{action} admin PIN for '{label}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or update a ResaPrint admin PIN.")
    parser.add_argument("--label", required=True, help="Human label shown in the admin UI, e.g. 'Recepcija'")
    parser.add_argument("--pin", help="The PIN value. If omitted, you'll be prompted (input hidden).")
    args = parser.parse_args()

    pin = args.pin or getpass.getpass("PIN: ")
    if not pin:
        parser.error("PIN must not be empty")

    asyncio.run(create_or_update_pin(args.label, pin))


if __name__ == "__main__":
    main()
