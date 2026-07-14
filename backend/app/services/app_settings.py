from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.app_settings import AppSettings
from app.services.crypto import encrypt

_SETTINGS_ID = 1


async def get_or_create_settings(db: AsyncSession) -> AppSettings:
    """Returns the singleton settings row, seeding it from env vars
    (backend/.env) on first access — this makes the transition from
    env-only config to GUI-editable config transparent for existing
    deployments."""
    result = await db.execute(select(AppSettings).where(AppSettings.id == _SETTINGS_ID))
    row = result.scalar_one_or_none()
    if row is not None:
        return row

    row = AppSettings(
        id=_SETTINGS_ID,
        imap_host=settings.imap_host or None,
        imap_port=settings.imap_port,
        imap_user=settings.imap_user or None,
        imap_folder=settings.imap_folder,
        imap_processed_folder=settings.imap_processed_folder,
        imap_poll_seconds=settings.imap_poll_seconds,
    )
    if settings.imap_password:
        row.imap_password_encrypted = encrypt(settings.imap_password)

    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row
