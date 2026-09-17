import os
from typing import AsyncGenerator, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

# Default to local SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentscope.db")

# Normalize PostgreSQL schemes to asyncpg if standard scheme provided
if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
elif DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+asyncpg://", 1)

# Configure engine options based on dialect
engine_kwargs = {"echo": False}
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    try:
        pool_size = int(os.getenv("DB_POOL_SIZE", "10"))
    except ValueError:
        pool_size = 10
    try:
        max_overflow = int(os.getenv("DB_MAX_OVERFLOW", "20"))
    except ValueError:
        max_overflow = 20

    engine_kwargs.update(
        {
            "pool_pre_ping": True,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
        }
    )

# Create asynchronous engine
engine = create_async_engine(DATABASE_URL, **engine_kwargs)


# Listen to connect event to configure SQLite options (WAL & Foreign Keys)
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    # Only execute SQLite-specific pragmas for SQLite dialect
    if engine.dialect.name != "sqlite":
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    finally:
        cursor.close()


async def vacuum_database(bind: Optional[AsyncEngine] = None) -> None:
    """Run VACUUM on a SQLite database to reclaim free space and defragment.

    SQLite cannot VACUUM inside a transaction, so the statement runs on an
    AUTOCOMMIT connection rather than relying on the driver deferring BEGIN.
    """
    target = bind or engine
    if target.dialect.name != "sqlite":
        return
    async with target.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT")
        await conn.execute(text("VACUUM"))


# Async session factory
async_session_maker = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for providing database sessions to FastAPI endpoints."""
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()
