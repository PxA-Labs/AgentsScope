"""Concurrent writers against a real file-backed SQLite database (issue #323).

Several SDK clients writing at once used to lose most of their events to
``sqlite3.OperationalError: database is locked``. These tests drive the real
event handler and REST write endpoints concurrently against a WAL-mode SQLite
file configured exactly like production, then count the stored rows.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

import database
import main
import pytest
import pytest_asyncio
from database import Base, get_db
from httpx import ASGITransport, AsyncClient
from main import app
from models import EventModel, SessionModel
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PRODUCERS = 10
EVENTS_PER_PRODUCER = 10


@pytest_asyncio.fixture
async def file_db(tmp_path, monkeypatch):
    """A fresh SQLite file with the production pragmas (WAL, busy_timeout)."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concurrent.db'}")
    event.listen(engine.sync_engine, "connect", database.set_sqlite_pragma)
    maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(database, "async_session_maker", maker)
    monkeypatch.setattr(main, "async_session_maker", maker)

    async def _get_db():
        async with maker() as session:
            yield session

    # The suite-wide override shares one session across requests; concurrent
    # requests need their own sessions, as in production.
    app.dependency_overrides[get_db] = _get_db
    try:
        yield maker
    finally:
        app.dependency_overrides.pop(get_db, None)
        await engine.dispose()


def _sdk_event(producer: int, k: int) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "parent_event_id": None,
        "event_type": "chain_start",
        "agent_name": f"agent-{producer}",
        "agent_type": "chain",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_ms": None,
        "status": "running",
        "payload": {"k": k},
    }


async def _produce(session_id: str, producer: int, count: int) -> None:
    """Send events one message at a time, like an SDK client's WebSocket loop."""
    for k in range(count):
        await main.handle_sdk_event(
            {
                "type": "event",
                "session_id": session_id,
                "event": _sdk_event(producer, k),
            }
        )


async def _count(maker, model) -> int:
    async with maker() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar()


def _db_errors(caplog) -> list:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.ERROR and "database" in r.getMessage().lower()
    ]


@pytest.mark.asyncio
async def test_concurrent_sdk_clients_store_every_event(file_db, caplog):
    session_ids = [f"conc-{uuid.uuid4().hex[:8]}" for _ in range(PRODUCERS)]

    with caplog.at_level(logging.ERROR):
        await asyncio.gather(
            *(
                _produce(sid, i, EVENTS_PER_PRODUCER)
                for i, sid in enumerate(session_ids)
            )
        )

    assert await _count(file_db, EventModel) == PRODUCERS * EVENTS_PER_PRODUCER
    assert await _count(file_db, SessionModel) == PRODUCERS
    assert _db_errors(caplog) == []


@pytest.mark.asyncio
async def test_sdk_events_survive_concurrent_rest_writes(file_db, caplog):
    """A single SDK stream must not lose events to REST writes running alongside."""
    stream_id = f"stream-{uuid.uuid4().hex[:8]}"
    events_sent = 40

    async def rest_writer(ac: AsyncClient, n: int) -> None:
        sid = f"rest-{n}-{uuid.uuid4().hex[:6]}"
        r = await ac.post("/api/sessions", json={"session_id": sid, "name": sid})
        assert r.status_code == 201, r.text
        r = await ac.patch(f"/api/sessions/{sid}", json={"status": "completed"})
        assert r.status_code == 200, r.text
        if n % 2:
            r = await ac.delete(f"/api/sessions/{sid}")
            assert r.status_code == 204, r.text

    with caplog.at_level(logging.ERROR):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            await asyncio.gather(
                _produce(stream_id, 0, events_sent),
                *(rest_writer(ac, n) for n in range(20)),
            )

    assert await _count(file_db, EventModel) == events_sent
    assert _db_errors(caplog) == []


@pytest.mark.asyncio
async def test_write_lock_does_not_serialise_postgresql():
    """Only SQLite needs one writer at a time; PostgreSQL writers stay parallel."""
    pg = create_async_engine("postgresql+asyncpg://user:pw@localhost/db")
    try:
        inside = 0
        peak = 0

        async def writer() -> None:
            nonlocal inside, peak
            async with database.sqlite_write_lock(pg):
                inside += 1
                peak = max(peak, inside)
                await asyncio.sleep(0.01)
                inside -= 1

        await asyncio.gather(*(writer() for _ in range(5)))
        assert peak == 5
    finally:
        await pg.dispose()


@pytest.mark.asyncio
async def test_write_lock_serialises_sqlite(file_db):
    inside = 0
    peak = 0

    async def writer() -> None:
        nonlocal inside, peak
        async with database.sqlite_write_lock(file_db):
            inside += 1
            peak = max(peak, inside)
            await asyncio.sleep(0.01)
            inside -= 1

    await asyncio.gather(*(writer() for _ in range(5)))
    assert peak == 1
