import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_db, require_admin_session_html
from app.models.admin_pin import AdminPin
from app.models.audit_log import AuditLog
from app.models.parser_mapping import (
    ExtractionType,
    FieldTransform,
    ParserFieldMapping,
    ParserFieldMappingField,
)
from app.models.print_job import PrintJob
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation
from app.schemas.config import ConfigOut
from app.schemas.parser import PARSED_RESERVATION_FIELDS
from app.services import audit, printing
from app.services.app_settings import get_or_create_settings
from app.services.crypto import encrypt
from app.services.parser_registry import GenericFieldMappingParser

router = APIRouter(tags=["admin-ui"])
templates = Jinja2Templates(directory="app/templates")


def _config_out(row) -> ConfigOut:
    return ConfigOut(
        imap_host=row.imap_host,
        imap_port=row.imap_port,
        imap_user=row.imap_user,
        imap_has_password=bool(row.imap_password_encrypted),
        imap_folder=row.imap_folder,
        imap_processed_folder=row.imap_processed_folder,
        imap_poll_seconds=row.imap_poll_seconds,
    )
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
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    reservations = (await db.execute(select(Reservation).order_by(Reservation.created_at.desc()))).scalars().all()
    return templates.TemplateResponse(request, "reservations/list.html", {"admin": admin, "reservations": reservations})


@router.get("/reservations/{reservation_id}")
async def reservation_detail_page(
    reservation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    reservation = await db.get(Reservation, reservation_id)
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
    reservation = await db.get(Reservation, reservation_id)
    station = await db.get(PrintStation, station_id)
    if reservation is None or station is None or not station.is_active:
        return templates.TemplateResponse(
            request, "reservations/_print_status.html", {"error": "reservation or station not found"}
        )

    text_summary, escpos_bytes = printing.build_reservation_receipt(reservation, station)
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
    admin: AdminPin = Depends(require_admin_session_html),
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
    admin: AdminPin = Depends(require_admin_session_html),
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
    admin: AdminPin = Depends(require_admin_session_html),
):
    station = await db.get(PrintStation, station_id)
    api_key = secrets.token_urlsafe(32)
    station.api_key_hash = _pwd_context.hash(api_key)
    station.api_key_prefix = api_key[:12]
    station.paired_at = datetime.now(timezone.utc)
    await audit.log(db, actor=admin.label, action="station.paired", entity_type="print_station", entity_id=station.id)
    await db.commit()
    return templates.TemplateResponse(request, "stations/_pairing_modal.html", {"api_key": api_key})


@router.get("/parsers")
async def parsers_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
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
    admin: AdminPin = Depends(require_admin_session_html),
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
    admin: AdminPin = Depends(require_admin_session_html),
):
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
    admin: AdminPin = Depends(require_admin_session_html),
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
    _admin: AdminPin = Depends(require_admin_session_html),
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
    admin: AdminPin = Depends(require_admin_session_html),
):
    entries = (await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500))).scalars().all()
    return templates.TemplateResponse(request, "audit_log/list.html", {"admin": admin, "entries": entries})


@router.get("/settings")
async def settings_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
):
    row = await get_or_create_settings(db)
    return templates.TemplateResponse(request, "settings.html", {"admin": admin, "config": _config_out(row), "saved": False})


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
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_session_html),
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

    await audit.log(db, actor=admin.label, action="config.updated", entity_type="app_settings", entity_id=row.id)
    await db.commit()
    await db.refresh(row)

    return templates.TemplateResponse(request, "settings.html", {"admin": admin, "config": _config_out(row), "saved": True})
