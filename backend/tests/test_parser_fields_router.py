import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parser_mapping import ParserFieldMapping, ParserFieldMappingField


@pytest.mark.asyncio
async def test_add_field_persists_group_index_and_required(authed_client: AsyncClient, db_session: AsyncSession):
    await authed_client.post("/parsers", data={"profile_slug": "test_profile", "match_subject_regex": ""})
    mapping = (await db_session.execute(select(ParserFieldMapping))).scalars().one()

    response = await authed_client.post(
        f"/parsers/{mapping.id}/fields",
        data={
            "label": "Ref",
            "target_field": "external_ref",
            "extraction_type": "regex",
            "pattern": r"Reservation number:\s*<span[^>]*>(\d+)",
            "group_index": "1",
            "transform": "none",
            "is_required": "true",
        },
    )
    assert response.status_code == 200

    field = (await db_session.execute(select(ParserFieldMappingField))).scalars().one()
    assert field.group_index == 1
    assert field.is_required is True

    response_unchecked = await authed_client.post(
        f"/parsers/{mapping.id}/fields",
        data={
            "label": "Optional field",
            "target_field": "guest_phone",
            "extraction_type": "regex",
            "pattern": r"Phone:\s*(.+)",
            "transform": "none",
            # is_required omitted entirely — simulates an unchecked checkbox
        },
    )
    assert response_unchecked.status_code == 200
    fields = (await db_session.execute(select(ParserFieldMappingField))).scalars().all()
    optional_field = next(f for f in fields if f.target_field == "guest_phone")
    assert optional_field.is_required is False


@pytest.mark.asyncio
async def test_update_field_action_changes_pattern_and_label(authed_client: AsyncClient, db_session: AsyncSession):
    await authed_client.post("/parsers", data={"profile_slug": "test_profile2", "match_subject_regex": ""})
    mapping = (await db_session.execute(select(ParserFieldMapping))).scalars().one()
    await authed_client.post(
        f"/parsers/{mapping.id}/fields",
        data={
            "label": "Old label",
            "target_field": "guest_name",
            "extraction_type": "regex",
            "pattern": r"Guest:\s*(.+)",
            "transform": "none",
            "is_required": "true",
        },
    )
    field = (await db_session.execute(select(ParserFieldMappingField))).scalars().one()

    response = await authed_client.post(
        f"/parsers/{mapping.id}/fields/{field.id}",
        data={
            "label": "New label",
            "target_field": "guest_name",
            "extraction_type": "regex",
            "pattern": r"Guestname:\s*(.+)",
            "group_index": "1",
            "transform": "strip",
            # is_required omitted — renaming the checkbox to unchecked
        },
    )
    assert response.status_code == 200
    assert "New label" in response.text

    await db_session.refresh(field)
    assert field.label == "New label"
    assert field.pattern == r"Guestname:\s*(.+)"
    assert field.transform.value == "strip"
    assert field.is_required is False


@pytest.mark.asyncio
async def test_delete_field_action_removes_field(authed_client: AsyncClient, db_session: AsyncSession):
    await authed_client.post("/parsers", data={"profile_slug": "test_profile3", "match_subject_regex": ""})
    mapping = (await db_session.execute(select(ParserFieldMapping))).scalars().one()
    await authed_client.post(
        f"/parsers/{mapping.id}/fields",
        data={
            "label": "To delete",
            "target_field": "guest_name",
            "extraction_type": "regex",
            "pattern": r"Guest:\s*(.+)",
            "transform": "none",
            "is_required": "true",
        },
    )
    field = (await db_session.execute(select(ParserFieldMappingField))).scalars().one()

    response = await authed_client.post(f"/parsers/{mapping.id}/fields/{field.id}/delete")
    assert response.status_code == 200
    assert "To delete" not in response.text

    remaining = (await db_session.execute(select(ParserFieldMappingField))).scalars().all()
    assert remaining == []
