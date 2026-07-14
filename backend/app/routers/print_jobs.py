from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_db, require_admin_session, require_station_key
from app.models.admin_pin import AdminPin
from app.models.print_job import PrintJob, PrintJobStatus
from app.models.print_station import PrintStation
from app.schemas.print_job import AckRequest, ManualPrintJobCreate, PrintJobOut
from app.services import audit
from app.services.escpos_builder import ReceiptBuilder

router = APIRouter(prefix="/api/v1/print-jobs", tags=["print-jobs"])


@router.get("", response_model=list[PrintJobOut])
async def list_print_jobs(
    status_filter: PrintJobStatus | None = None,
    station_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> list[PrintJob]:
    query = select(PrintJob).order_by(PrintJob.created_at.desc())
    if status_filter is not None:
        query = query.where(PrintJob.status == status_filter)
    if station_id is not None:
        query = query.where(PrintJob.station_id == station_id)
    result = await db.execute(query)
    return list(result.scalars().all())


@router.get("/poll", response_model=list[PrintJobOut])
async def poll_print_jobs(
    db: AsyncSession = Depends(get_db),
    station: PrintStation = Depends(require_station_key),
) -> list[PrintJob]:
    result = await db.execute(
        select(PrintJob).where(PrintJob.station_id == station.id, PrintJob.status == PrintJobStatus.queued)
    )
    jobs = list(result.scalars().all())
    for job in jobs:
        job.status = PrintJobStatus.sent
        job.sent_at = datetime.now(timezone.utc)
    await db.commit()
    for job in jobs:
        await db.refresh(job)
    return jobs


@router.get("/{job_id}", response_model=PrintJobOut)
async def get_print_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session),
) -> PrintJob:
    job = await db.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="print job not found")
    return job


@router.post("", response_model=PrintJobOut, status_code=status.HTTP_201_CREATED)
async def create_manual_print_job(
    payload: ManualPrintJobCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> PrintJob:
    station = await db.get(PrintStation, payload.station_id)
    if station is None or not station.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="station not found or inactive")

    builder = ReceiptBuilder(codepage=station.codepage)
    for line in payload.payload_text.splitlines() or [""]:
        builder.line(line)
    builder.feed(3).cut()

    job = PrintJob(
        station_id=station.id,
        status=PrintJobStatus.queued,
        payload_text=payload.payload_text,
        escpos_bytes=builder.build(),
        requested_by=admin.label,
    )
    db.add(job)
    await db.flush()

    if station.connection_type.value == "lan_escpos":
        from app.services.printing import dispatch_lan_job

        await dispatch_lan_job(db, job, station)

    await audit.log(db, actor=admin.label, action="print_job.created_manual", entity_type="print_job", entity_id=job.id)
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/retry", response_model=PrintJobOut)
async def retry_print_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> PrintJob:
    job = await db.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="print job not found")

    station = await db.get(PrintStation, job.station_id)
    job.status = PrintJobStatus.queued
    job.last_error = None

    if station and station.connection_type.value == "lan_escpos":
        from app.services.printing import dispatch_lan_job

        await dispatch_lan_job(db, job, station)

    await audit.log(db, actor=admin.label, action="print_job.retried", entity_type="print_job", entity_id=job.id)
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=PrintJobOut)
async def cancel_print_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session),
) -> PrintJob:
    job = await db.get(PrintJob, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="print job not found")

    job.status = PrintJobStatus.cancelled
    await audit.log(db, actor=admin.label, action="print_job.cancelled", entity_type="print_job", entity_id=job.id)
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/ack", response_model=PrintJobOut)
async def ack_print_job(
    job_id: int,
    payload: AckRequest,
    db: AsyncSession = Depends(get_db),
    station: PrintStation = Depends(require_station_key),
) -> PrintJob:
    job = await db.get(PrintJob, job_id)
    if job is None or job.station_id != station.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="print job not found")

    job.status = payload.status
    job.attempts += 1
    if payload.status == PrintJobStatus.printed:
        job.printed_at = datetime.now(timezone.utc)
    if payload.status == PrintJobStatus.failed:
        job.last_error = payload.error

    await audit.log(
        db,
        actor=station.name,
        action="print_job.ack",
        entity_type="print_job",
        entity_id=job.id,
        detail={"status": payload.status.value, "error": payload.error},
    )
    await db.commit()
    await db.refresh(job)
    return job
