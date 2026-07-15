from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin_session
from app.models.admin_pin import AdminPin
from app.schemas.config import ConfigOut, ConfigUpdate
from app.services import audit
from app.services.app_settings import get_or_create_settings
from app.services.crypto import encrypt

router = APIRouter(prefix="/api/v1/config", tags=["config"])


def _to_out(row) -> ConfigOut:
    return ConfigOut(
        imap_host=row.imap_host,
        imap_port=row.imap_port,
        imap_user=row.imap_user,
        imap_has_password=bool(row.imap_password_encrypted),
        imap_folder=row.imap_folder,
        imap_processed_folder=row.imap_processed_folder,
        imap_poll_seconds=row.imap_poll_seconds,
        auto_print_enabled=row.auto_print_enabled,
        auto_print_station_id=row.auto_print_station_id,
    )


@router.get("", response_model=ConfigOut)
async def get_config(
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> ConfigOut:
    row = await get_or_create_settings(db)
    return _to_out(row)


@router.patch("", response_model=ConfigOut)
async def update_config(
    payload: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> ConfigOut:
    row = await get_or_create_settings(db)

    data = payload.model_dump(exclude_unset=True)
    password = data.pop("imap_password", None)
    if password:
        row.imap_password_encrypted = encrypt(password)

    for field, value in data.items():
        setattr(row, field, value)

    await audit.log(db, actor=admin.label, action="config.updated", entity_type="app_settings", entity_id=row.id)
    await db.commit()
    await db.refresh(row)
    return _to_out(row)
