from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_db, require_admin_session
from app.models.admin_pin import AdminPin
from app.models.print_station import PrintStation
from app.models.reservation import Reservation, ReservationStatus
from app.schemas.reservation import (
    PrintRequest,
    ReservationCreate,
    ReservationOut,
    ReservationUpdate,
)
from app.services import audit, printing
from app.services.app_settings import get_or_create_settings

router = APIRouter(prefix="/api/v1/reservations", tags=["reservations"])


@router.get("", response_model=list[ReservationOut])
async def list_reservations(
    status_filter: ReservationStatus | None = None,
    source_channel: str | None = None,
    checkin_from: date | None = None,
    checkin_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> list[Reservation]:
    query = select(Reservation).order_by(Reservation.created_at.desc())
    if status_filter is not None:
        query = query.where(Reservation.status == status_filter)
    if source_channel is not None:
        query = query.where(Reservation.source_channel == source_channel)
    if checkin_from is not None:
        query = query.where(Reservation.checkin >= checkin_from)
    if checkin_to is not None:
        query = query.where(Reservation.checkin <= checkin_to)

    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/{reservation_id}", response_model=ReservationOut)
async def get_reservation(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> Reservation:
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reservation not found")
    return reservation


@router.post("", response_model=ReservationOut, status_code=status.HTTP_201_CREATED)
async def create_reservation(
    payload: ReservationCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> Reservation:
    reservation = Reservation(**payload.model_dump(), status=ReservationStatus.manual)
    db.add(reservation)
    await db.flush()
    await audit.log(
        db, actor=admin.label, action="reservation.created_manual", entity_type="reservation", entity_id=reservation.id
    )
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.patch("/{reservation_id}", response_model=ReservationOut)
async def update_reservation(
    reservation_id: int,
    payload: ReservationUpdate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> Reservation:
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reservation not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(reservation, field, value)

    await audit.log(
        db,
        actor=admin.label,
        action="reservation.manual_override",
        entity_type="reservation",
        entity_id=reservation.id,
        detail=payload.model_dump(exclude_unset=True, mode="json"),
    )
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.delete("/{reservation_id}", response_model=ReservationOut)
async def cancel_reservation(
    reservation_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> Reservation:
    reservation = await db.get(Reservation, reservation_id)
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reservation not found")

    reservation.status = ReservationStatus.cancelled
    await audit.log(
        db, actor=admin.label, action="reservation.cancelled", entity_type="reservation", entity_id=reservation.id
    )
    await db.commit()
    await db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/print")
async def print_reservation(
    reservation_id: int,
    payload: PrintRequest,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> dict:
    reservation = (
        await db.execute(
            select(Reservation).options(selectinload(Reservation.room_lines)).where(Reservation.id == reservation_id)
        )
    ).scalar_one_or_none()
    if reservation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="reservation not found")

    station = await db.get(PrintStation, payload.station_id)
    if station is None or not station.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="station not found or inactive")

    app_settings = await get_or_create_settings(db)
    text_summary, escpos_bytes = printing.build_reservation_receipt(reservation, station, app_settings)
    job = await printing.enqueue_print_job(
        db,
        station=station,
        reservation=reservation,
        payload_text=text_summary,
        escpos_bytes=escpos_bytes,
        requested_by=admin.label,
    )
    await audit.log(
        db,
        actor=admin.label,
        action="print_job.created",
        entity_type="print_job",
        entity_id=job.id,
        detail={"reservation_id": reservation.id, "station_id": station.id},
    )
    await db.commit()
    return {"print_job_id": job.id, "status": job.status.value}
