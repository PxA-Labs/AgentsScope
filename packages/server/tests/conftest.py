import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import database
import main
import pytest_asyncio
from database import Base, get_db
from main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Temporary file database for testing to avoid SQLite connection isolation traps
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_temp.db"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    # Remove old database file if it exists to ensure a clean state
    for suffix in ["", "-journal", "-wal"]:
        path = f"./test_temp.db{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    engine = create_async_engine(TEST_DATABASE_URL)

    # Patch the global session maker in both database and main modules
    test_session_maker = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    database.async_session_maker = test_session_maker
    main.async_session_maker = test_session_maker
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

    # Clean up temp database files
    for suffix in ["", "-journal", "-wal"]:
        path = f"./test_temp.db{suffix}"
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


@pytest_asyncio.fixture
async def db_session(db_engine):
    session_maker = async_sessionmaker(
        bind=db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        yield session


@pytest_asyncio.fixture(autouse=True)
async def override_get_db(db_session):
    async def _get_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()
