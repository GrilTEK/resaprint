from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  registers all models on Base.metadata
from app.db import Base, get_db
from app.main import app

# SQLite in-memory for tests: fast, no external service needed. None of
# our models use Postgres-only types (JSONB/ARRAY/etc — we use the
# dialect-generic sa.JSON), so this is a faithful enough substitute for
# unit/API tests. Real deployments always run against Postgres via
# docker-compose + alembic (see backend-ci.yml for a Postgres-backed run).
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _get_db_override() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    transport = ASGITransport(app=app)
    # https:// base_url (not http://) so the httpx cookie jar honors the
    # session cookie's Secure attribute across requests within a test.
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def authed_client(client: AsyncClient, db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from app.models.admin_pin import AdminPin
    from app.services.auth_service import hash_pin

    db_session.add(AdminPin(label="Test admin", pin_hash=hash_pin("1234")))
    await db_session.commit()

    response = await client.post("/login", data={"pin": "1234"})
    assert response.status_code == 200
    yield client


@pytest_asyncio.fixture
async def reception_client(client: AsyncClient, db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """A second, independently-cookied client authenticated as a
    reception-role PIN — for asserting admin-only routes reject it.
    Depends on `client` only to guarantee the get_db override is
    already installed; it does not reuse `client`'s cookie jar."""
    from app.models.admin_pin import AdminPin, AdminRole
    from app.services.auth_service import hash_pin

    db_session.add(AdminPin(label="Test reception", pin_hash=hash_pin("5678"), role=AdminRole.reception))
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as ac:
        response = await ac.post("/login", data={"pin": "5678"})
        assert response.status_code == 200
        yield ac
