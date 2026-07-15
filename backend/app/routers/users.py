from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin_role
from app.models.admin_pin import AdminPin, AdminRole
from app.schemas.user import UserCreate, UserOut, UserUpdate
from app.services import audit
from app.services.auth_service import hash_pin

router = APIRouter(prefix="/api/v1/users", tags=["users"])


async def _count_other_active_admins(db: AsyncSession, exclude_id: int) -> int:
    result = await db.execute(
        select(func.count()).select_from(AdminPin).where(
            AdminPin.role == AdminRole.admin, AdminPin.is_active.is_(True), AdminPin.id != exclude_id
        )
    )
    return result.scalar_one()


@router.get("", response_model=list[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_role),
) -> list[AdminPin]:
    result = await db.execute(select(AdminPin).order_by(AdminPin.label))
    return list(result.scalars().all())


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> AdminPin:
    user = AdminPin(label=payload.label, role=payload.role, pin_hash=hash_pin(payload.pin))
    db.add(user)
    await db.flush()
    await audit.log(db, actor=admin.label, action="user.created", entity_type="admin_pin", entity_id=user.id)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> AdminPin:
    user = await db.get(AdminPin, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    data = payload.model_dump(exclude_unset=True)
    pin = data.pop("pin", None)

    demoting = "role" in data and data["role"] != AdminRole.admin and user.role == AdminRole.admin
    deactivating = data.get("is_active") is False and user.is_active

    if (demoting or deactivating) and await _count_other_active_admins(db, exclude_id=user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot demote/deactivate the last active admin user",
        )

    for field, value in data.items():
        setattr(user, field, value)
    if pin:
        user.pin_hash = hash_pin(pin)
        user.failed_attempts = 0
        user.locked_until = None

    await audit.log(db, actor=admin.label, action="user.updated", entity_type="admin_pin", entity_id=user.id)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> None:
    user = await db.get(AdminPin, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    if user.role == AdminRole.admin and await _count_other_active_admins(db, exclude_id=user.id) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cannot delete the last active admin user")

    await audit.log(
        db, actor=admin.label, action="user.deleted", entity_type="admin_pin", entity_id=user.id,
        detail={"label": user.label},
    )
    await db.delete(user)
    await db.commit()
