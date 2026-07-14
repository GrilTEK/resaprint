from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin_session
from app.models.admin_pin import AdminPin
from app.models.audit_log import AuditLog
from app.schemas.audit_log import AuditLogOut

router = APIRouter(prefix="/api/v1/audit-log", tags=["audit-log"])


@router.get("", response_model=list[AuditLogOut])
async def list_audit_log(
    actor: str | None = None,
    action: str | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> list[AuditLog]:
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)
    if actor is not None:
        query = query.where(AuditLog.actor == actor)
    if action is not None:
        query = query.where(AuditLog.action == action)
    result = await db.execute(query)
    return list(result.scalars().all())
