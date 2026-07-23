import os
from typing import AsyncGenerator
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
    AsyncSession,
)
from sqlalchemy.orm import declarative_base

# Default to local SQLite file
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./agentscope.db")

# Create asynchronous engine
engine = create_async_engine(DATABASE_URL, echo=False)


# Listen to connect event to configure SQLite options (WAL & Foreign Keys)
@event.listens_for(engine.sync_engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    finally:
        cursor.close()


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
