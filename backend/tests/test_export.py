import csv
import io
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.room import Room


@pytest.mark.asyncio
async def test_export_page_lists_tables(authed_client: AsyncClient):
    response = await authed_client.get("/export")
    assert response.status_code == 200
    assert "Reservations" in response.text
    assert "/export/rooms.csv" in response.text


@pytest.mark.asyncio
async def test_export_table_csv(authed_client: AsyncClient, db_session: AsyncSession):
    db_session.add(Room(room_number="101", category="Double"))
    await db_session.commit()

    response = await authed_client.get("/export/rooms.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"] == 'attachment; filename="rooms.csv"'

    rows = list(csv.reader(io.StringIO(response.text)))
    assert rows[0][:3] == ["id", "room_number", "category"]
    assert any(row[1] == "101" and row[2] == "Double" for row in rows[1:])


@pytest.mark.asyncio
async def test_export_unknown_table_404(authed_client: AsyncClient):
    response = await authed_client.get("/export/not-a-table.csv")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_database_zip_contains_every_table(authed_client: AsyncClient, db_session: AsyncSession):
    db_session.add(Room(room_number="102", category="Single"))
    await db_session.commit()

    response = await authed_client.get("/export/database.zip")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        assert "reservations.csv" in names
        assert "rooms.csv" in names
        assert "users.csv" in names

        rooms_csv = zf.read("rooms.csv").decode()
        assert "102" in rooms_csv

        # secrets never leak into the export
        users_csv = zf.read("users.csv").decode()
        assert "pin_hash" not in users_csv.lower()
