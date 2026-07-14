from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.print_job import PrintJob, PrintJobStatus
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation
from app.services.escpos_builder import ReceiptBuilder


def build_reservation_receipt(reservation: Reservation, station: PrintStation) -> tuple[str, bytes]:
    width = station.paper_width_cols
    nights = max((reservation.checkout - reservation.checkin).days, 0)

    builder = ReceiptBuilder(codepage=station.codepage)
    builder.align_center().bold_line("ResaPrint")
    builder.divider(width)
    builder.align_left()
    builder.kv_line("Guest:", reservation.guest_name, width=width)
    builder.kv_line("Check-in:", reservation.checkin.isoformat(), width=width)
    builder.kv_line("Check-out:", reservation.checkout.isoformat(), width=width)
    if reservation.external_ref:
        builder.kv_line("Ref#:", reservation.external_ref, width=width)

    text_lines = [
        f"Guest: {reservation.guest_name}",
        f"Check-in: {reservation.checkin.isoformat()}",
        f"Check-out: {reservation.checkout.isoformat()}",
        f"Ref#: {reservation.external_ref or '-'}",
    ]

    if reservation.room_lines:
        builder.divider(width)
        for line in reservation.room_lines:
            builder.line(line.room_type)
            if line.nights is not None:
                builder.kv_line("  Nights:", str(line.nights), width=width)
            if line.price_per_night is not None:
                builder.kv_line("  Per night:", f"{reservation.price_currency} {line.price_per_night}", width=width)
            if line.price_total is not None:
                builder.kv_line("  Line total:", f"{reservation.price_currency} {line.price_total}", width=width)
            text_lines.append(
                f"Room: {line.room_type} | nights={line.nights or '-'} "
                f"per_night={line.price_per_night or '-'} total={line.price_total or '-'}"
            )
    elif reservation.room_type:
        builder.kv_line("Room:", reservation.room_type, width=width)
        text_lines.append(f"Room: {reservation.room_type}")

    if reservation.price_total is not None:
        builder.divider(width)
        builder.kv_line("Total:", f"{reservation.price_currency} {reservation.price_total}", width=width)
        text_lines.append(f"Total: {reservation.price_currency} {reservation.price_total}")
        if nights > 0:
            avg_per_night = reservation.price_total / nights
            builder.kv_line("Avg/night:", f"{reservation.price_currency} {avg_per_night:.2f}", width=width)
            text_lines.append(f"Avg/night: {reservation.price_currency} {avg_per_night:.2f}")

    builder.divider(width)
    builder.line(f"Printed {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    builder.feed(3).cut()

    text_summary = "\n".join(text_lines) + "\n"
    return text_summary, builder.build()


async def send_lan_escpos(host: str, port: int, payload: bytes, timeout: float | None = None) -> None:
    timeout = timeout if timeout is not None else settings.lan_print_timeout_seconds
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=timeout)
    try:
        writer.write(payload)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def enqueue_print_job(
    db: AsyncSession,
    *,
    station: PrintStation,
    reservation: Reservation | None,
    payload_text: str,
    escpos_bytes: bytes,
    requested_by: str | None,
) -> PrintJob:
    job = PrintJob(
        reservation_id=reservation.id if reservation else None,
        station_id=station.id,
        status=PrintJobStatus.queued,
        payload_text=payload_text,
        escpos_bytes=escpos_bytes,
        requested_by=requested_by,
    )
    db.add(job)
    await db.flush()

    if station.connection_type == StationConnectionType.lan_escpos:
        await dispatch_lan_job(db, job, station)

    await db.commit()
    await db.refresh(job)
    return job


async def dispatch_lan_job(db: AsyncSession, job: PrintJob, station: PrintStation) -> None:
    job.attempts += 1
    try:
        await send_lan_escpos(station.lan_host, station.lan_port, job.escpos_bytes)
    except (OSError, asyncio.TimeoutError) as exc:
        job.status = PrintJobStatus.failed
        job.last_error = str(exc)
        return

    job.status = PrintJobStatus.printed
    job.sent_at = datetime.now(timezone.utc)
    job.printed_at = datetime.now(timezone.utc)
