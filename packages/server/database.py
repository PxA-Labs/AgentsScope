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


# Configure SQLite options (WAL & Foreign Keys) on every new connection.
# Registered only on SQLite engines by configure_sqlite_engine, so it does not
# depend on the global engine's dialect: a SQLite engine built while
# DATABASE_URL points at PostgreSQL still gets its pragmas.
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
    finally:
        cursor.close()


def _disable_driver_begin(dbapi_connection, connection_record) -> None:
    # sqlite3 (and so aiosqlite) only emits BEGIN before INSERT/UPDATE/DELETE.
    # A SAVEPOINT opened outside a transaction then commits on RELEASE, so a
    # later ROLLBACK cannot undo it (#329). SQLAlchemy emits BEGIN instead.
    dbapi_connection.isolation_level = None


def _emit_begin(conn) -> None:
    # VACUUM runs on an AUTOCOMMIT connection and must stay outside BEGIN.
    if conn.get_execution_options().get("isolation_level") == "AUTOCOMMIT":
        return
    # Returning an AUTOCOMMIT connection to the pool resets the driver to its
    # legacy mode; switch it back before this transaction starts.
    dbapi_connection = conn.connection.dbapi_connection
    if dbapi_connection.isolation_level is not None:
        dbapi_connection.isolation_level = None
    conn.exec_driver_sql("BEGIN")


def configure_sqlite_engine(target: AsyncEngine) -> None:
    """Apply the production SQLite settings to ``target``.

    Sets the pragmas on each connection and lets SQLAlchemy emit BEGIN at the
    start of every transaction (SQLAlchemy's documented recipe for SAVEPOINT
    support on sqlite3/aiosqlite), so ``begin_nested()`` is nested in a real
    transaction and commits or rolls back with it.

    Does nothing when ``target`` is not a SQLite engine: the check uses the
    engine's own dialect, never the global ``engine``.
    """
    if target.dialect.name != "sqlite":
        return
    sync_engine = target.sync_engine
    event.listen(sync_engine, "connect", set_sqlite_pragma)
    event.listen(sync_engine, "connect", _disable_driver_begin)
    event.listen(sync_engine, "begin", _emit_begin)


def create_engine_for_url(url: str, **kwargs: Any) -> AsyncEngine:
    """Create an async engine, configured for SQLite when ``url`` is SQLite."""
    new_engine = create_async_engine(url, **kwargs)
    if new_engine.dialect.name == "sqlite":
        configure_sqlite_engine(new_engine)
    return new_engine


# Create asynchronous engine
engine = create_engine_for_url(DATABASE_URL, **engine_kwargs)


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
