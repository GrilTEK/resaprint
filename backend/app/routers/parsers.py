from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.deps import get_db, require_admin_role
from app.models.admin_pin import AdminPin
from app.models.parser_mapping import ParserFieldMapping, ParserFieldMappingField
from app.schemas.parser_admin import (
    ParserFieldCreate,
    ParserFieldMappingCreate,
    ParserFieldMappingOut,
    ParserTestRequest,
    ParserTestResult,
)
from app.services import audit
from app.services.parser_registry import GenericFieldMappingParser, ParserError

router = APIRouter(prefix="/api/v1/parsers", tags=["parsers"])


async def _get_mapping_or_404(db: AsyncSession, mapping_id: int) -> ParserFieldMapping:
    result = await db.execute(
        select(ParserFieldMapping)
        .options(selectinload(ParserFieldMapping.fields))
        .where(ParserFieldMapping.id == mapping_id)
    )
    mapping = result.scalar_one_or_none()
    if mapping is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="parser profile not found")
    return mapping


@router.get("", response_model=list[ParserFieldMappingOut])
async def list_parsers(
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_role),
) -> list[ParserFieldMapping]:
    result = await db.execute(
        select(ParserFieldMapping).options(selectinload(ParserFieldMapping.fields))
    )
    return list(result.scalars().all())


@router.post("", response_model=ParserFieldMappingOut, status_code=status.HTTP_201_CREATED)
async def create_parser(
    payload: ParserFieldMappingCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> ParserFieldMapping:
    mapping = ParserFieldMapping(**payload.model_dump())
    db.add(mapping)
    await db.flush()
    await audit.log(db, actor=admin.label, action="parser.created", entity_type="parser_field_mapping", entity_id=mapping.id)
    await db.commit()
    return await _get_mapping_or_404(db, mapping.id)


@router.patch("/{mapping_id}", response_model=ParserFieldMappingOut)
async def update_parser(
    mapping_id: int,
    payload: ParserFieldMappingCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> ParserFieldMapping:
    mapping = await _get_mapping_or_404(db, mapping_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(mapping, field, value)
    await audit.log(db, actor=admin.label, action="parser.updated", entity_type="parser_field_mapping", entity_id=mapping.id)
    await db.commit()
    return await _get_mapping_or_404(db, mapping_id)


@router.delete("/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parser(
    mapping_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> None:
    mapping = await _get_mapping_or_404(db, mapping_id)
    await db.delete(mapping)
    await audit.log(db, actor=admin.label, action="parser.deleted", entity_type="parser_field_mapping", entity_id=mapping_id)
    await db.commit()


@router.post("/{mapping_id}/fields", response_model=ParserFieldMappingOut, status_code=status.HTTP_201_CREATED)
async def add_parser_field(
    mapping_id: int,
    payload: ParserFieldCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> ParserFieldMapping:
    mapping = await _get_mapping_or_404(db, mapping_id)
    field = ParserFieldMappingField(mapping_id=mapping.id, **payload.model_dump())
    db.add(field)
    await audit.log(
        db, actor=admin.label, action="parser.field_added",
        entity_type="parser_field_mapping", entity_id=mapping.id,
    )
    await db.commit()
    return await _get_mapping_or_404(db, mapping_id)


@router.patch("/{mapping_id}/fields/{field_id}", response_model=ParserFieldMappingOut)
async def update_parser_field(
    mapping_id: int,
    field_id: int,
    payload: ParserFieldCreate,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> ParserFieldMapping:
    field = await db.get(ParserFieldMappingField, field_id)
    if field is None or field.mapping_id != mapping_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="field not found")
    for attr, value in payload.model_dump(exclude_unset=True).items():
        setattr(field, attr, value)
    await audit.log(
        db, actor=admin.label, action="parser.field_updated",
        entity_type="parser_field_mapping", entity_id=mapping_id,
    )
    await db.commit()
    return await _get_mapping_or_404(db, mapping_id)


@router.delete("/{mapping_id}/fields/{field_id}", response_model=ParserFieldMappingOut)
async def delete_parser_field(
    mapping_id: int,
    field_id: int,
    db: AsyncSession = Depends(get_db),
    admin: AdminPin = Depends(require_admin_role),
) -> ParserFieldMapping:
    field = await db.get(ParserFieldMappingField, field_id)
    if field is None or field.mapping_id != mapping_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="field not found")
    await db.delete(field)
    await audit.log(
        db, actor=admin.label, action="parser.field_deleted",
        entity_type="parser_field_mapping", entity_id=mapping_id,
    )
    await db.commit()
    return await _get_mapping_or_404(db, mapping_id)


@router.post("/{mapping_id}/test", response_model=ParserTestResult)
async def test_parser(
    mapping_id: int,
    payload: ParserTestRequest,
    db: AsyncSession = Depends(get_db),
    _admin: AdminPin = Depends(require_admin_role),
) -> ParserTestResult:
    mapping = await _get_mapping_or_404(db, mapping_id)
    parser = GenericFieldMappingParser(mapping)

    matched = parser.can_parse(payload.subject, payload.body, payload.content_type)
    if not matched:
        return ParserTestResult(matched=False)

    try:
        parsed = parser.parse(payload.subject, payload.body, payload.content_type)
    except ParserError as exc:
        return ParserTestResult(matched=True, error=str(exc))

    return ParserTestResult(matched=True, parsed=parsed.model_dump(mode="json"))
