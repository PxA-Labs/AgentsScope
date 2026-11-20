import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

if "mem0" not in sys.modules:
    try:
        import mem0  # noqa: F401
    except Exception:
        from unittest.mock import MagicMock

        mock_mem0 = MagicMock()
        mock_mem0.MemoryClient = MagicMock
        sys.modules["mem0"] = mock_mem0

import database
import main
import pytest_asyncio
from database import Base, get_db
from main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture(scope="session")
async def db_engine(tmp_path_factory):
    """A file-backed SQLite engine configured like production (#333).

    create_engine_for_url applies WAL, foreign_keys, busy_timeout and lets
    SQLAlchemy emit BEGIN, so the suite runs under the production settings.
    """
    db_path = tmp_path_factory.mktemp("db") / "test.db"
    engine = database.create_engine_for_url(f"sqlite+aiosqlite:///{db_path}")

    # Patch the global session maker in both database and main modules
    test_session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    database.async_session_maker = test_session_maker
    main.async_session_maker = test_session_maker
    try:
        import retention

        retention.async_session_maker = test_session_maker
    except ImportError:
        pass
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_maker(db_engine):
    return async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest_asyncio.fixture
async def db_session(db_session_maker):
    """A session for seeding and checking data directly in a test.

    Requests do not share it (see override_get_db), so a read after a request
    needs a new transaction (commit/rollback) or a fresh session to see the
    request's writes.
    """
    async with db_session_maker() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def override_get_db(db_session_maker):
    # One session per request, as in production get_db.
    async def _get_db():
        async with db_session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def file_db(tmp_path, monkeypatch):
    """A fresh SQLite file configured like production (WAL, busy_timeout, BEGIN)."""
    engine = database.create_engine_for_url(
        f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}"
    )
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(main, "async_session_maker", maker)

    async def _get_db():
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    try:
        yield maker
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()
