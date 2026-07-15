from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin_role
from app.models.admin_pin import AdminPin
from app.models.room import Room
from app.schemas.room import RoomCreate, RoomOut, RoomUpdate
from app.services import audit

router = APIRouter(prefix="/api/v1/rooms", tags=["rooms"])


@router.get("", response_model=list[RoomOut])
async def list_rooms(
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_role),
) -> list[Room]:
    result = await db.execute(select(Room).order_by(Room.room_number))
    return list(result.scalars().all())


@router.post("", response_model=RoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    payload: RoomCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> Room:
    room = Room(**payload.model_dump())
    db.add(room)
    await db.flush()
    await audit.log(db, actor=admin.label, action="room.created", entity_type="room", entity_id=room.id)
    await db.commit()
    await db.refresh(room)
    return room


@router.patch("/{room_id}", response_model=RoomOut)
async def update_room(
    room_id: int,
    payload: RoomUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="room not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(room, field, value)

    await audit.log(
        db, actor=admin.label, action="room.updated", entity_type="room", entity_id=room.id,
        detail=payload.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    await db.refresh(room)
    return room


@router.delete("/{room_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_room(
    room_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> None:
    """Hard delete. Any reservation/room-line currently assigned to
    this room has its assignment cleared (FK ON DELETE SET NULL) —
    the reservation itself is untouched."""
    room = await db.get(Room, room_id)
    if room is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="room not found")

    await audit.log(
        db, actor=admin.label, action="room.deleted", entity_type="room", entity_id=room.id,
        detail={"room_number": room.room_number},
    )
    await db.delete(room)
    await db.commit()
