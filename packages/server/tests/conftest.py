import pytest_asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

import models
from database import Base, get_db
from main import app

print("CONFTEST Base ID:", id(Base))
print("MODELS Base ID:", id(models.Base))
print("MODELS registry tables:", list(models.Base.metadata.tables.keys()))


# Temporary file database for testing to avoid SQLite connection isolation traps
TEST_DATABASE_URL = "sqlite+aiosqlite:///./test_temp.db"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL)
    print("REGISTRY TABLES BEFORE CREATE:", list(Base.metadata.tables.keys()))
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
