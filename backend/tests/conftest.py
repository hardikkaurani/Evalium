import asyncio
import os
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("APP_ENV", "testing")
# Ensure host environment variables like DEBUG='release' do not taint test Settings
if os.environ.get("DEBUG") and os.environ.get("DEBUG").lower() in ("release", "debug"):
    os.environ.pop("DEBUG", None)

# Ensure root, cli, and sdk/python are in sys.path
ROOT_DIR = Path(__file__).resolve().parents[2]
for path_entry in [
    str(ROOT_DIR),
    str(ROOT_DIR / "cli"),
    str(ROOT_DIR / "sdk" / "python"),
]:
    if path_entry not in sys.path:
        sys.path.insert(0, path_entry)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.enterprise.models  # noqa: F401, E402
import app.jobs.models.job  # noqa: F401, E402
import app.models.advanced_ai  # noqa: F401, E402
import app.models.analytics  # noqa: F401, E402
import app.models.dataset  # noqa: F401, E402
import app.models.evaluation  # noqa: F401, E402

# Import all models to ensure complete SQLAlchemy metadata registration
import app.models.project  # noqa: F401, E402
import app.platform.models  # noqa: F401, E402
from app.core.redis import redis_manager  # noqa: E402
from app.database.session import Base  # noqa: E402
from app.main import app  # noqa: E402

# SQLite in-memory database URL for testing async sessions
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session", autouse=True)
def mock_redis() -> Generator[None, None, None]:
    """Mocks redis_manager connectivity to prevent dependency errors during test runs."""
    ping_mock = AsyncMock(return_value=True)
    close_mock = AsyncMock()
    with (
        patch.object(redis_manager, "ping", ping_mock),
        patch.object(redis_manager, "init", return_value=None),
        patch.object(redis_manager, "close", close_mock),
    ):
        yield


@pytest.fixture(name="db_session")
def db_session_fixture() -> Generator[AsyncSession, None, None]:
    """Initializes schema on in-memory SQLite synchronously, yields session,

    and drops tables on teardown.
    """
    loop = asyncio.new_event_loop()

    engine = create_async_engine(
        TEST_DATABASE_URL, connect_args={"check_same_thread": False}
    )
    TestingSessionLocal = async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    # Run table creation synchronously in the loop
    async def create_tables():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    loop.run_until_complete(create_tables())

    # Patch application SessionLocal bind to point to testing engine
    from app.database.session import SessionLocal

    SessionLocal.configure(bind=engine)

    session = TestingSessionLocal()

    yield session

    # Run cleanup synchronously in the loop
    async def destroy_tables():
        await session.close()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    loop.run_until_complete(destroy_tables())
    loop.close()


@pytest.fixture(name="auth_headers")
def auth_headers_fixture() -> dict[str, str]:
    """Returns headers containing a mock API key for authenticated requests."""
    return {"X-API-Key": "test_api_key_evalforge_qa"}


@pytest.fixture(name="client")
def client_fixture(
    db_session: AsyncSession,
) -> Generator[TestClient, None, None]:
    """Overrides get_db and get_current_api_key dependencies, returning a TestClient."""
    from unittest.mock import MagicMock

    from app.core.dependencies import get_current_api_key, get_db

    mock_key_record = MagicMock()
    mock_key_record.id = "key_test_123"
    mock_key_record.name = "Test API Key"

    async def override_get_db():
        yield db_session

    async def override_get_current_api_key(
        x_api_key: str | None = None,
    ):
        if x_api_key == "invalid_key":
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="Invalid or inactive API key.")
        return mock_key_record

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_api_key] = override_get_current_api_key

    with TestClient(app) as test_client:
        test_client.headers.update({"X-API-Key": "test_api_key_evalforge_qa"})
        yield test_client
    app.dependency_overrides.clear()
