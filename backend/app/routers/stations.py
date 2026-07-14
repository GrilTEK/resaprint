import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin_session
from app.models.admin_pin import AdminPin
from app.models.print_station import PrintStation
from app.schemas.print_station import PairResponse, PrintStationCreate, PrintStationOut
from app.services import audit

router = APIRouter(prefix="/api/v1/stations", tags=["stations"])
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("", response_model=list[PrintStationOut])
async def list_stations(
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> list[PrintStation]:
    result = await db.execute(select(PrintStation).order_by(PrintStation.name))
    return list(result.scalars().all())


@router.post("", response_model=PrintStationOut, status_code=status.HTTP_201_CREATED)
async def create_station(
    payload: PrintStationCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> PrintStation:
    station = PrintStation(**payload.model_dump())
    db.add(station)
    await db.flush()
    await audit.log(db, actor=admin.label, action="station.created", entity_type="print_station", entity_id=station.id)
    await db.commit()
    await db.refresh(station)
    return station


@router.post("/{station_id}/pair", response_model=PairResponse)
async def pair_station(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> PairResponse:
    station = await db.get(PrintStation, station_id)
    if station is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="station not found")

    api_key = secrets.token_urlsafe(32)
    station.api_key_hash = _pwd_context.hash(api_key)
    station.api_key_prefix = api_key[:12]
    station.paired_at = datetime.now(timezone.utc)

    await audit.log(db, actor=admin.label, action="station.paired", entity_type="print_station", entity_id=station.id)
    await db.commit()
    return PairResponse(station_id=station.id, api_key=api_key)


@router.delete("/{station_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_station(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> None:
    """Hard delete — the row is actually removed (and its print job
    history cascade-deleted via the FK), freeing up the station's
    unique name for reuse. If you just want to temporarily stop a
    station without losing its history, revoke its pairing instead of
    deleting it."""
    station = await db.get(PrintStation, station_id)
    if station is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="station not found")

    await audit.log(
        db, actor=admin.label, action="station.deleted", entity_type="print_station", entity_id=station.id,
        detail={"name": station.name},
    )
    await db.delete(station)
    await db.commit()


@router.get("/{station_id}/status", response_model=PrintStationOut)
async def station_status(
    station_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> PrintStation:
    station = await db.get(PrintStation, station_id)
    if station is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="station not found")
    return station
