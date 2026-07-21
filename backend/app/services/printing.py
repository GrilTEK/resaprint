from __future__ import annotations

import asyncio
import textwrap
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.app_settings import AppSettings
from app.models.print_job import PrintJob, PrintJobStatus
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation, ReservationStatus
from app.services.escpos_builder import ReceiptBuilder


def _room_label(room_type: str, assigned_room) -> str:
    if assigned_room is not None:
        return f"{room_type} (Soba {assigned_room.room_number})"
    return room_type


def _wrap(text: str, width: int) -> list[str]:
    return textwrap.wrap(text, width=width) or [text]


def build_reservation_receipt(
    reservation: Reservation,
    station: PrintStation,
    app_settings: AppSettings | None = None,
) -> tuple[str, bytes]:
    """Layout modeled on the operator's previous standalone print
    script: a source-channel title, "Gost/Sobe/From/To/GOSTI|NOČI"
    body, then a dashed-divider "SKUPAJ" total and reservation number
    footer — kept close to that familiar wording rather than the more
    generic English labels used before."""
    width = station.paper_width_cols
    nights = max((reservation.checkout - reservation.checkin).days, 0)
    guests = (reservation.guests_adults or 0) + (reservation.guests_children or 0)
    is_cancelled = reservation.status == ReservationStatus.cancelled

    # app_settings is optional (defaults below) so existing callers/tests
    # that don't care about receipt layout customization keep working.
    font = app_settings.receipt_font if app_settings else "font_a"
    font_size = app_settings.receipt_font_size if app_settings else "normal"
    bold_labels = app_settings.receipt_bold_labels if app_settings else False
    show_nights = app_settings.receipt_show_nights if app_settings else True
    show_guests = app_settings.receipt_show_guests if app_settings else True
    show_channel = app_settings.receipt_show_channel if app_settings else True

    base_size = {"large": (2, 2), "xlarge": (3, 3)}.get(font_size, (1, 1))

    builder = ReceiptBuilder(codepage=station.codepage, bold_labels=bold_labels)
    builder.set_font(font)  # type: ignore[arg-type]
    builder.set_text_size(*base_size)

    header = f"{reservation.source_channel.upper()} REZERVACIJA" if show_channel else "REZERVACIJA"
    if is_cancelled:
        header += " — PREKLICANO"
    builder.align_center().bold_line(header)

    def _cancelled_banner() -> None:
        # A word in the header title isn't enough on its own — cheap
        # thermal printers, a torn-off top edge, or a distracted staff
        # member skimming the receipt could all miss it. A large bold
        # banner top and bottom makes "this reservation is cancelled"
        # impossible to miss on the physical paper.
        builder.set_text_size(3, 3)
        builder.bold_line("*** PREKLICANO ***")
        builder.set_text_size(*base_size)

    if is_cancelled:
        _cancelled_banner()
    builder.divider(width)
    builder.align_left()

    text_lines = [header]
    if is_cancelled:
        text_lines.append("*** PREKLICANO ***")
    builder.kv_line("Gost:", reservation.guest_name, width=width)
    text_lines.append(f"Gost: {reservation.guest_name}")

    if reservation.room_lines:
        builder.line("Sobe:")
        text_lines.append("Sobe:")
        for line in reservation.room_lines:
            label = _room_label(line.room_type, line.assigned_room)
            wrapped = _wrap(label, width)
            builder.line(wrapped[0])
            text_lines.append(wrapped[0])
            for cont in wrapped[1:]:
                builder.line(f"  {cont}")
                text_lines.append(f"  {cont}")
            if line.nights is not None:
                builder.kv_line("  Nights:", str(line.nights), width=width)
                text_lines.append(f"  Nights: {line.nights}")
            if line.price_per_night is not None:
                builder.kv_line("  Per night:", f"{reservation.price_currency} {line.price_per_night}", width=width)
                text_lines.append(f"  Per night: {reservation.price_currency} {line.price_per_night}")
            if line.price_total is not None:
                builder.kv_line("  Line total:", f"{reservation.price_currency} {line.price_total}", width=width)
                text_lines.append(f"  Line total: {reservation.price_currency} {line.price_total}")
    elif reservation.room_type:
        label = _room_label(reservation.room_type, reservation.assigned_room)
        builder.line("Sobe:")
        text_lines.append("Sobe:")
        wrapped = _wrap(label, width)
        builder.line(wrapped[0])
        text_lines.append(wrapped[0])
        for cont in wrapped[1:]:
            builder.line(f"  {cont}")
            text_lines.append(f"  {cont}")

    builder.kv_line("From:", reservation.checkin.isoformat(), width=width)
    builder.kv_line("To:", reservation.checkout.isoformat(), width=width)
    text_lines.append(f"From: {reservation.checkin.isoformat()}")
    text_lines.append(f"To: {reservation.checkout.isoformat()}")

    if show_guests and show_nights:
        summary_line = f"GOSTI: {guests}  |  NOČI: {nights}"
    elif show_guests:
        summary_line = f"GOSTI: {guests}"
    elif show_nights:
        summary_line = f"NOČI: {nights}"
    else:
        summary_line = None
    if summary_line:
        builder.line(summary_line)
        text_lines.append(summary_line)

    builder.divider(width)
    text_lines.append("-" * width)
    if reservation.price_total is not None:
        builder.kv_line("SKUPAJ:", f"{reservation.price_currency} {reservation.price_total}", width=width)
        text_lines.append(f"SKUPAJ: {reservation.price_currency} {reservation.price_total}")
        if nights > 0:
            avg_per_night = reservation.price_total / nights
            builder.kv_line("Povp./noč:", f"{reservation.price_currency} {avg_per_night:.2f}", width=width)
            text_lines.append(f"Povp./noč: {reservation.price_currency} {avg_per_night:.2f}")
        builder.divider(width)
        text_lines.append("-" * width)
    builder.kv_line("Reservation nr.:", reservation.external_ref or "-", width=width)
    text_lines.append(f"Reservation nr.: {reservation.external_ref or '-'}")

    builder.divider(width)
    if is_cancelled:
        builder.align_center()
        _cancelled_banner()
        builder.align_left()
        text_lines.append("*** PREKLICANO ***")
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
