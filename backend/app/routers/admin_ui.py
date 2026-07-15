import secrets
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_db, require_admin_role_html, require_admin_session_html
from app.models.admin_pin import AdminPin, AdminRole
from app.models.audit_log import AuditLog
from app.models.parser_mapping import (
    ExtractionType,
    FieldTransform,
    ParserFieldMapping,
    ParserFieldMappingField,
)
from app.models.print_job import PrintJob
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation, ReservationStatus
from app.models.reservation_room_line import ReservationRoomLine
from app.models.room import Room
from app.schemas.config import config_out_from_row
from app.schemas.parser import PARSED_RESERVATION_FIELDS
from app.services import audit, printing
from app.services.app_settings import get_or_create_settings
from app.services.auth_service import hash_pin
from app.services.crypto import encrypt
from app.services.parser_registry import GenericFieldMappingParser
from app.services.room_assignment import reassign_rooms_for_reservation, rooms_occupied_on_date

router = APIRouter(tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")
_config_out = config_out_from_row

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"admin": None})


@router.get("/")
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    today = date.today()
    arrivals = (
        await db.execute(select(Reservation).where(Reservation.checkin == today).order_by(Reservation.guest_name))
    ).scalars().all()
    jobs = (await db.execute(select(PrintJob).order_by(PrintJob.created_at.desc()).limit(20))).scalars().all()
    stations = (await db.execute(select(PrintStation).order_by(PrintStation.name))).scalars().all()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"admin": admin, "todays_arrivals": arrivals, "print_jobs": jobs, "stations": stations},
    )


@router.get("/reservations")
async def reservations_page(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    query = select(Reservation).order_by(Reservation.created_at.desc())
    if q:
        like = f"%{q}%"
        query = query.where(
            or_(
                Reservation.guest_name.ilike(like),
                Reservation.guest_email.ilike(like),
                Reservation.guest_phone.ilike(like),
                Reservation.external_ref.ilike(like),
                Reservation.room_type.ilike(like),
            )
        )
    reservations = (await db.execute(query)).scalars().all()
    return templates.TemplateResponse(
        request, "reservations/list.html", {"admin": admin, "reservations": reservations, "q": q}
    )


def _sheet_rows(reservations: list[Reservation]) -> list[dict]:
    """Flattens each reservation into one row per room line (or a
    single virtual row using the legacy room_type field, for
    reservations with no room lines) so the sheet can show/assign a
    room per booked unit rather than per reservation."""
    rows = []
    for r in reservations:
        if r.room_lines:
            for line in r.room_lines:
                rows.append(
                    {
                        "reservation": r,
                        "room_line_id": line.id,
                        "category": line.room_type,
                        "assigned_room": line.assigned_room,
                    }
                )
        else:
            rows.append(
                {"reservation": r, "room_line_id": None, "category": r.room_type, "assigned_room": r.assigned_room}
            )
    return rows


async def _sheet_context(db: AsyncSession, admin: AdminPin, sheet_date: date) -> dict:
    reservations = (
        await db.execute(
            select(Reservation)
            .options(
                selectinload(Reservation.room_lines).selectinload(ReservationRoomLine.assigned_room),
                selectinload(Reservation.assigned_room),
            )
            .where(Reservation.checkin == sheet_date, Reservation.status != ReservationStatus.cancelled)
            .order_by(Reservation.guest_name)
        )
    ).scalars().all()
    rooms = (await db.execute(select(Room).where(Room.is_active.is_(True)).order_by(Room.room_number))).scalars().all()
    stations = (
        await db.execute(select(PrintStation).where(PrintStation.is_active.is_(True)).order_by(PrintStation.name))
    ).scalars().all()
    occupied = await rooms_occupied_on_date(db, sheet_date)

    return {
        "admin": admin,
        "rows": _sheet_rows(reservations),
        "rooms": rooms,
        "stations": stations,
        "occupied": occupied,
        "sheet_date": sheet_date,
        "prev_date": sheet_date - timedelta(days=1),
        "next_date": sheet_date + timedelta(days=1),
    }


@router.get("/reservations/sheet")
async def reservations_sheet_page(
    request: Request,
    sheet_date: date = Query(default_factory=date.today, alias="date"),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    context = await _sheet_context(db, admin, sheet_date)
    return templates.TemplateResponse(request, "reservations/sheet.html", context)


@router.post("/reservations/{reservation_id}/assign-and-print")
async def assign_and_print_action(
    reservation_id: int,
    request: Request,
    sheet_date: date = Form(..., alias="sheet_date"),
    room_id: str = Form(default=""),
    room_line_id: str = Form(default=""),
    station_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    reservation = (
        await db.execute(
            select(Reservation)
            .options(
                selectinload(Reservation.room_lines).selectinload(ReservationRoomLine.assigned_room),
                selectinload(Reservation.assigned_room),
            )
            .where(Reservation.id == reservation_id)
        )
    ).scalar_one_or_none()
    station = await db.get(PrintStation, station_id)

    if reservation is not None and station is not None and station.is_active:
        room_id_value = int(room_id) if room_id else None
        if room_line_id:
            line = next((line for line in reservation.room_lines if line.id == int(room_line_id)), None)
            if line is not None:
                line.assigned_room_id = room_id_value
        else:
            reservation.assigned_room_id = room_id_value
        await audit.log(
            db, actor=admin.label, action="reservation.room_assigned_manually", entity_type="reservation",
            entity_id=reservation.id, detail={"room_id": room_id_value, "room_line_id": room_line_id or None},
        )
        await db.flush()

        app_settings = await get_or_create_settings(db)
        text_summary, escpos_bytes = printing.build_reservation_receipt(reservation, station, app_settings)
        job = await printing.enqueue_print_job(
            db, station=station, reservation=reservation, payload_text=text_summary, escpos_bytes=escpos_bytes,
            requested_by=admin.label,
        )
        await audit.log(
            db, actor=admin.label, action="print_job.created", entity_type="print_job", entity_id=job.id,
            detail={"reservation_id": reservation.id, "station_id": station.id},
        )
        await db.commit()

    context = await _sheet_context(db, admin, sheet_date)
    return templates.TemplateResponse(request, "reservations/sheet.html", context)


@router.get("/reservations/{reservation_id}")
async def reservation_detail_page(
    reservation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    reservation = (
        await db.execute(
            select(Reservation)
            .options(
                selectinload(Reservation.room_lines).selectinload(ReservationRoomLine.assigned_room),
                selectinload(Reservation.assigned_room),
            )
            .where(Reservation.id == reservation_id)
        )
    ).scalar_one_or_none()
    stations = (
        await db.execute(select(PrintStation).where(PrintStation.is_active.is_(True)).order_by(PrintStation.name))
    ).scalars().all()
    return templates.TemplateResponse(
        request, "reservations/detail.html", {"admin": admin, "reservation": reservation, "stations": stations}
    )


@router.post("/reservations/{reservation_id}/print")
async def reservation_print_action(
    reservation_id: int,
    request: Request,
    station_id: int = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    reservation = (
        await db.execute(
            select(Reservation)
            .options(
                selectinload(Reservation.room_lines).selectinload(ReservationRoomLine.assigned_room),
                selectinload(Reservation.assigned_room),
            )
            .where(Reservation.id == reservation_id)
        )
    ).scalar_one_or_none()
    station = await db.get(PrintStation, station_id)
    if reservation is None or station is None or not station.is_active:
        return templates.TemplateResponse(
            request, "reservations/_print_status.html", {"error": "reservation or station not found"}
        )

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
    return templates.TemplateResponse(
        request,
        "reservations/_print_status.html",
        {"print_job_id": job.id, "job_status": job.status.value},
    )


@router.get("/print-jobs")
async def print_jobs_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    jobs = (await db.execute(select(PrintJob).order_by(PrintJob.created_at.desc()).limit(200))).scalars().all()
    return templates.TemplateResponse(request, "print_jobs/list.html", {"admin": admin, "print_jobs": jobs})


@router.get("/print-jobs/table")
async def print_jobs_table(
    request: Request,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_session_html),
):
    jobs = (await db.execute(select(PrintJob).order_by(PrintJob.created_at.desc()).limit(200))).scalars().all()
    return templates.TemplateResponse(request, "print_jobs/_table_body.html", {"print_jobs": jobs})


@router.get("/stations")
async def stations_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    stations = (await db.execute(select(PrintStation).order_by(PrintStation.name))).scalars().all()
    return templates.TemplateResponse(request, "stations/list.html", {"admin": admin, "stations": stations})


@router.post("/stations")
async def create_station_action(
    request: Request,
    name: str = Form(...),
    connection_type: StationConnectionType = Form(...),
    lan_host: str = Form(default=""),
    lan_port: int = Form(default=9100),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    station = PrintStation(
        name=name,
        connection_type=connection_type,
        lan_host=lan_host or None,
        lan_port=lan_port,
    )
    db.add(station)
    await db.flush()
    await audit.log(db, actor=admin.label, action="station.created", entity_type="print_station", entity_id=station.id)
    await db.commit()

    stations = (await db.execute(select(PrintStation).order_by(PrintStation.name))).scalars().all()
    return templates.TemplateResponse(request, "stations/list.html", {"admin": admin, "stations": stations})


@router.post("/stations/{station_id}/pair")
async def pair_station_action(
    station_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    station = await db.get(PrintStation, station_id)
    api_key = secrets.token_urlsafe(32)
    station.api_key_hash = _pwd_context.hash(api_key)
    station.api_key_prefix = api_key[:12]
    station.paired_at = datetime.now(timezone.utc)
    await audit.log(db, actor=admin.label, action="station.paired", entity_type="print_station", entity_id=station.id)
    await db.commit()
    return templates.TemplateResponse(request, "stations/_pairing_modal.html", {"api_key": api_key})


@router.post("/stations/{station_id}/delete")
async def delete_station_action(
    station_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    station = await db.get(PrintStation, station_id)
    if station is not None:
        await audit.log(
            db, actor=admin.label, action="station.deleted", entity_type="print_station", entity_id=station.id,
            detail={"name": station.name},
        )
        await db.delete(station)
        await db.commit()

    stations = (await db.execute(select(PrintStation).order_by(PrintStation.name))).scalars().all()
    return templates.TemplateResponse(request, "stations/list.html", {"admin": admin, "stations": stations})


@router.get("/parsers")
async def parsers_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    mappings = (
        await db.execute(select(ParserFieldMapping).options(selectinload(ParserFieldMapping.fields)))
    ).scalars().all()
    return templates.TemplateResponse(request, "parsers/list.html", {"admin": admin, "mappings": mappings})


@router.post("/parsers")
async def create_parser_action(
    request: Request,
    profile_slug: str = Form(...),
    match_subject_regex: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    mapping = ParserFieldMapping(profile_slug=profile_slug, match_subject_regex=match_subject_regex or None)
    db.add(mapping)
    await db.flush()
    await audit.log(db, actor=admin.label, action="parser.created", entity_type="parser_field_mapping", entity_id=mapping.id)
    await db.commit()

    mappings = (
        await db.execute(select(ParserFieldMapping).options(selectinload(ParserFieldMapping.fields)))
    ).scalars().all()
    return templates.TemplateResponse(request, "parsers/list.html", {"admin": admin, "mappings": mappings})


async def _mapping_or_404(db: AsyncSession, mapping_id: int) -> ParserFieldMapping:
    result = await db.execute(
        select(ParserFieldMapping)
        .options(selectinload(ParserFieldMapping.fields))
        .where(ParserFieldMapping.id == mapping_id)
    )
    return result.scalar_one()


@router.get("/parsers/{mapping_id}")
async def parser_detail_page(
    mapping_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    mapping = await _mapping_or_404(db, mapping_id)
    return templates.TemplateResponse(
        request,
        "parsers/_mapping_form.html",
        {"admin": admin, "mapping": mapping, "target_fields": sorted(PARSED_RESERVATION_FIELDS)},
    )


@router.post("/parsers/{mapping_id}/room-line-pattern")
async def update_room_line_pattern_action(
    mapping_id: int,
    request: Request,
    room_line_pattern: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    mapping = await _mapping_or_404(db, mapping_id)
    mapping.room_line_pattern = room_line_pattern or None
    await audit.log(
        db, actor=admin.label, action="parser.room_line_pattern_updated",
        entity_type="parser_field_mapping", entity_id=mapping.id,
    )
    await db.commit()

    mapping = await _mapping_or_404(db, mapping_id)
    return templates.TemplateResponse(
        request,
        "parsers/_mapping_form.html",
        {"admin": admin, "mapping": mapping, "target_fields": sorted(PARSED_RESERVATION_FIELDS)},
    )


@router.post("/parsers/{mapping_id}/fields")
async def add_parser_field_action(
    mapping_id: int,
    request: Request,
    label: str = Form(...),
    target_field: str = Form(...),
    extraction_type: ExtractionType = Form(...),
    pattern: str = Form(...),
    transform: FieldTransform = Form(default=FieldTransform.none),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    field = ParserFieldMappingField(
        mapping_id=mapping_id,
        label=label,
        target_field=target_field,
        extraction_type=extraction_type,
        pattern=pattern,
        transform=transform,
    )
    db.add(field)
    await audit.log(
        db, actor=admin.label, action="parser.field_added",
        entity_type="parser_field_mapping", entity_id=mapping_id,
    )
    await db.commit()

    mapping = await _mapping_or_404(db, mapping_id)
    return templates.TemplateResponse(
        request,
        "parsers/_mapping_form.html",
        {"admin": admin, "mapping": mapping, "target_fields": sorted(PARSED_RESERVATION_FIELDS)},
    )


@router.post("/parsers/{mapping_id}/test")
async def test_parser_action(
    mapping_id: int,
    request: Request,
    subject: str = Form(default=""),
    body: str = Form(...),
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_role_html),
):
    mapping = await _mapping_or_404(db, mapping_id)
    parser = GenericFieldMappingParser(mapping)

    matched = parser.can_parse(subject, body, "text/plain")
    result = {"matched": matched, "parsed": None, "error": None}
    if matched:
        try:
            parsed = parser.parse(subject, body, "text/plain")
            result["parsed"] = parsed.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001 — surfaced to the operator, not swallowed
            result["error"] = str(exc)

    return templates.TemplateResponse(request, "parsers/_test_result.html", {"result": result})


@router.get("/audit-log")
async def audit_log_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    entries = (await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500))).scalars().all()
    return templates.TemplateResponse(request, "audit_log/list.html", {"admin": admin, "entries": entries})


@router.get("/settings")
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    row = await get_or_create_settings(db)
    stations = (
        await db.execute(select(PrintStation).where(PrintStation.is_active.is_(True)).order_by(PrintStation.name))
    ).scalars().all()
    return templates.TemplateResponse(
        request, "settings.html", {"admin": admin, "config": _config_out(row), "stations": stations, "saved": False}
    )


@router.post("/settings")
async def settings_update_action(
    request: Request,
    imap_host: str = Form(default=""),
    imap_port: int = Form(default=993),
    imap_user: str = Form(default=""),
    imap_password: str = Form(default=""),
    imap_folder: str = Form(default="INBOX"),
    imap_processed_folder: str = Form(default="Processed"),
    imap_poll_seconds: int = Form(default=60),
    auto_print_enabled: bool = Form(default=False),
    auto_print_station_id: str = Form(default=""),
    room_auto_assign_enabled: bool = Form(default=False),
    receipt_font: str = Form(default="font_a"),
    receipt_font_size: str = Form(default="normal"),
    receipt_bold_labels: bool = Form(default=False),
    receipt_show_nights: bool = Form(default=False),
    receipt_show_guests: bool = Form(default=False),
    receipt_show_channel: bool = Form(default=False),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    row = await get_or_create_settings(db)
    row.imap_host = imap_host or None
    row.imap_port = imap_port
    row.imap_user = imap_user or None
    row.imap_folder = imap_folder
    row.imap_processed_folder = imap_processed_folder
    row.imap_poll_seconds = imap_poll_seconds
    if imap_password:
        row.imap_password_encrypted = encrypt(imap_password)

    row.auto_print_enabled = auto_print_enabled
    row.auto_print_station_id = int(auto_print_station_id) if auto_print_station_id else None
    row.room_auto_assign_enabled = room_auto_assign_enabled

    row.receipt_font = receipt_font
    row.receipt_font_size = receipt_font_size
    row.receipt_bold_labels = receipt_bold_labels
    row.receipt_show_nights = receipt_show_nights
    row.receipt_show_guests = receipt_show_guests
    row.receipt_show_channel = receipt_show_channel

    await audit.log(db, actor=admin.label, action="config.updated", entity_type="app_settings", entity_id=row.id)
    await db.commit()
    await db.refresh(row)

    stations = (
        await db.execute(select(PrintStation).where(PrintStation.is_active.is_(True)).order_by(PrintStation.name))
    ).scalars().all()
    return templates.TemplateResponse(
        request, "settings.html", {"admin": admin, "config": _config_out(row), "stations": stations, "saved": True}
    )


@router.get("/users")
async def users_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    users = (await db.execute(select(AdminPin).order_by(AdminPin.label))).scalars().all()
    return templates.TemplateResponse(request, "users/list.html", {"admin": admin, "users": users, "roles": list(AdminRole)})


@router.post("/users")
async def create_user_action(
    request: Request,
    label: str = Form(...),
    role: AdminRole = Form(...),
    pin: str = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):

    user = AdminPin(label=label, role=role, pin_hash=hash_pin(pin))
    db.add(user)
    await db.flush()
    await audit.log(db, actor=admin.label, action="user.created", entity_type="admin_pin", entity_id=user.id)
    await db.commit()

    users = (await db.execute(select(AdminPin).order_by(AdminPin.label))).scalars().all()
    return templates.TemplateResponse(request, "users/list.html", {"admin": admin, "users": users, "roles": list(AdminRole)})


@router.post("/users/{user_id}/delete")
async def delete_user_action(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):

    user = await db.get(AdminPin, user_id)
    error = None
    if user is not None:
        if user.role == AdminRole.admin:
            other_admins = (
                await db.execute(
                    select(func.count()).select_from(AdminPin).where(
                        AdminPin.role == AdminRole.admin, AdminPin.is_active.is_(True), AdminPin.id != user.id
                    )
                )
            ).scalar_one()
            if other_admins == 0:
                error = "Cannot delete the last active admin user."
        if error is None:
            await audit.log(
                db, actor=admin.label, action="user.deleted", entity_type="admin_pin", entity_id=user.id,
                detail={"label": user.label},
            )
            await db.delete(user)
            await db.commit()

    users = (await db.execute(select(AdminPin).order_by(AdminPin.label))).scalars().all()
    return templates.TemplateResponse(
        request, "users/list.html", {"admin": admin, "users": users, "roles": list(AdminRole), "error": error}
    )


@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active_action(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):

    user = await db.get(AdminPin, user_id)
    error = None
    if user is not None:
        if user.role == AdminRole.admin and user.is_active:
            other_admins = (
                await db.execute(
                    select(func.count()).select_from(AdminPin).where(
                        AdminPin.role == AdminRole.admin, AdminPin.is_active.is_(True), AdminPin.id != user.id
                    )
                )
            ).scalar_one()
            if other_admins == 0:
                error = "Cannot deactivate the last active admin user."
        if error is None:
            user.is_active = not user.is_active
            await audit.log(
                db, actor=admin.label, action="user.updated", entity_type="admin_pin", entity_id=user.id,
                detail={"is_active": user.is_active},
            )
            await db.commit()

    users = (await db.execute(select(AdminPin).order_by(AdminPin.label))).scalars().all()
    return templates.TemplateResponse(
        request, "users/list.html", {"admin": admin, "users": users, "roles": list(AdminRole), "error": error}
    )


@router.get("/rooms")
async def rooms_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    rooms = (await db.execute(select(Room).order_by(Room.room_number))).scalars().all()
    return templates.TemplateResponse(request, "rooms/list.html", {"admin": admin, "rooms": rooms})


@router.post("/rooms")
async def create_room_action(
    request: Request,
    room_number: str = Form(...),
    category: str = Form(...),
    floor: str = Form(default=""),
    notes: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    room = Room(room_number=room_number, category=category, floor=floor or None, notes=notes or None)
    db.add(room)
    await db.flush()
    await audit.log(db, actor=admin.label, action="room.created", entity_type="room", entity_id=room.id)
    await db.commit()

    rooms = (await db.execute(select(Room).order_by(Room.room_number))).scalars().all()
    return templates.TemplateResponse(request, "rooms/list.html", {"admin": admin, "rooms": rooms})


@router.post("/rooms/{room_id}/toggle-active")
async def toggle_room_active_action(
    room_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    room = await db.get(Room, room_id)
    if room is not None:
        room.is_active = not room.is_active
        await audit.log(
            db, actor=admin.label, action="room.updated", entity_type="room", entity_id=room.id,
            detail={"is_active": room.is_active},
        )
        await db.commit()

    rooms = (await db.execute(select(Room).order_by(Room.room_number))).scalars().all()
    return templates.TemplateResponse(request, "rooms/list.html", {"admin": admin, "rooms": rooms})


@router.post("/rooms/{room_id}/delete")
async def delete_room_action(
    room_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role_html),
):
    room = await db.get(Room, room_id)
    if room is not None:
        await audit.log(
            db, actor=admin.label, action="room.deleted", entity_type="room", entity_id=room.id,
            detail={"room_number": room.room_number},
        )
        await db.delete(room)
        await db.commit()

    rooms = (await db.execute(select(Room).order_by(Room.room_number))).scalars().all()
    return templates.TemplateResponse(request, "rooms/list.html", {"admin": admin, "rooms": rooms})


@router.post("/reservations/{reservation_id}/reassign-room")
async def reassign_room_action(
    reservation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    reservation = (
        await db.execute(
            select(Reservation).options(selectinload(Reservation.room_lines)).where(Reservation.id == reservation_id)
        )
    ).scalar_one_or_none()
    if reservation is not None:
        await reassign_rooms_for_reservation(db, reservation)
        await audit.log(
            db, actor=admin.label, action="reservation.room_reassigned", entity_type="reservation",
            entity_id=reservation.id,
        )
        await db.commit()

    reservation = (
        await db.execute(
            select(Reservation)
            .options(
                selectinload(Reservation.room_lines).selectinload(ReservationRoomLine.assigned_room),
                selectinload(Reservation.assigned_room),
            )
            .where(Reservation.id == reservation_id)
        )
    ).scalar_one_or_none()
    stations = (
        await db.execute(select(PrintStation).where(PrintStation.is_active.is_(True)).order_by(PrintStation.name))
    ).scalars().all()
    return templates.TemplateResponse(
        request, "reservations/detail.html", {"admin": admin, "reservation": reservation, "stations": stations}
    )
