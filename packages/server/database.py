import asyncio
import os
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, AsyncIterator, Optional

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


class _LoopLocalLock:
    """An asyncio.Lock that is recreated when used from a different event loop.

    asyncio.Lock binds to the first loop that waits on it, which would break
    a module-level lock across separate loops (e.g. one per test).
    """

    def __init__(self) -> None:
        self._lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def get(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._loop is not loop:
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._lock


_sqlite_writer = _LoopLocalLock()


def _dialect_name(target: Any) -> str:
    if isinstance(target, async_sessionmaker):
        target = target.kw.get("bind")
    elif isinstance(target, AsyncSession):
        target = target.get_bind()
    dialect = getattr(target, "dialect", None)
    return dialect.name if dialect is not None else ""


@asynccontextmanager
async def sqlite_write_lock(target: Any) -> AsyncIterator[None]:
    """Serialise database writes when ``target`` is backed by SQLite.

    SQLite allows one writer at a time, and a transaction that has already
    read (e.g. after SAVEPOINT + SELECT) and then needs the write lock gets
    SQLITE_BUSY / SQLITE_BUSY_SNAPSHOT immediately: busy_timeout does not
    apply, so concurrent writers drop data with "database is locked" (#323).
    Holding this lock around every write transaction in the process removes
    that contention. Other dialects (PostgreSQL) are not serialised.

    ``target`` is an AsyncSession, async_sessionmaker or AsyncEngine. When it
    is a session, it is rolled back before the lock is released if the block
    raises, so a failed transaction never keeps SQLite's write lock while the
    next writer starts.
    """
    if _dialect_name(target) != "sqlite":
        yield
        return
    async with _sqlite_writer.get():
        try:
            yield
        except BaseException:
            if isinstance(target, AsyncSession):
                await target.rollback()
            raise


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
