"""An SDK event and its session aggregates are stored atomically (issue #329).

``_persist_event`` writes the event inside a SAVEPOINT and then updates the
session totals. With the sqlite3 driver's legacy transaction handling, a
SAVEPOINT opened outside a transaction committed the event on RELEASE, so a
failure in the aggregate step left the event stored without its totals and
without a broadcast. These tests run against a real SQLite file configured
like production.
"""

import logging
import uuid
from datetime import datetime, timezone

import database
import main
import pytest
from models import EventModel, SessionModel
from sqlalchemy import event, false, func, select, text
from sqlalchemy.orm import Session


@pytest.fixture
def broadcasts(monkeypatch):
    """Record what would be sent to UI clients."""
    sent = []

    async def record(kind, *args, **kwargs):
        sent.append((kind, args, kwargs))

    for name in (
        "broadcast_to_session_ui",
        "broadcast_graph_update",
        "broadcast_session_update",
    ):

        async def _fn(*args, _name=name, **kwargs):
            await record(_name, *args, **kwargs)

        monkeypatch.setattr(main.manager, name, _fn)
    return sent


def _event(event_type="chain_start", status="running", **overrides) -> dict:
    data = {
        "event_id": str(uuid.uuid4()),
        "parent_event_id": None,
        "event_type": event_type,
        "agent_name": f"agent-{uuid.uuid4().hex[:6]}",
        "agent_type": "chain",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_ms": None,
        "status": status,
        "payload": {},
    }
    data.update(overrides)
    return data


def _llm_end(status="success", **overrides) -> dict:
    return _event(
        event_type="llm_end",
        status=status,
        payload={
            "model": "gpt-4o",
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "total_tokens": 30,
        },
        **overrides,
    )


async def _event_rows(maker, event_id: str) -> int:
    async with maker() as db:
        stmt = select(func.count()).where(EventModel.event_id == event_id)
        return (await db.execute(stmt)).scalar()


async def _session(maker, session_id: str) -> SessionModel:
    async with maker() as db:
        stmt = select(SessionModel).where(SessionModel.session_id == session_id)
        return (await db.execute(stmt)).scalars().one()


async def _started_session(maker) -> tuple:
    """A session that already holds one event, with its aggregates as stored."""
    sid = f"atomic-{uuid.uuid4().hex[:8]}"
    await main.process_single_event(_event(), sid)
    sess = await _session(maker, sid)
    totals = (sess.total_tokens, sess.error_count, sess.agent_count)
    return sid, totals


def _totals(sess: SessionModel) -> tuple:
    return (sess.total_tokens, sess.error_count, sess.agent_count)


def _fail_cost(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("injected aggregate failure")

    monkeypatch.setattr(main, "_calculate_llm_cost", boom)


async def _fail_session_update(maker):
    """Make the session aggregate UPDATE itself fail inside SQLite."""
    async with maker.kw["bind"].begin() as conn:
        await conn.execute(
            text(
                "CREATE TRIGGER fail_session_update BEFORE UPDATE ON sessions "
                "BEGIN SELECT RAISE(ABORT, 'injected aggregate failure'); END"
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("injection", ["aggregate_code", "aggregate_update"])
async def test_aggregate_failure_does_not_leave_event_stored(
    file_db, broadcasts, caplog, monkeypatch, injection
):
    sid, totals_before = await _started_session(file_db)
    broadcasts.clear()

    ev = _llm_end(status="error")
    if injection == "aggregate_code":
        _fail_cost(monkeypatch)
    else:
        await _fail_session_update(file_db)

    with caplog.at_level(logging.INFO):
        await main.process_single_event(ev, sid)

    assert await _event_rows(file_db, ev["event_id"]) == 0
    assert _totals(await _session(file_db, sid)) == totals_before
    assert broadcasts == []

    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO]
    failure = [m for m in messages if ev["event_id"] in m]
    assert len(failure) == 1, messages
    assert "event or session aggregates" in failure[0]
    assert "llm_end" in failure[0]
    assert sid in failure[0]
    assert "duplicate" not in failure[0]


@pytest.mark.asyncio
async def test_aggregate_failure_after_vacuum_is_still_atomic(
    file_db, broadcasts, monkeypatch
):
    """VACUUM runs in AUTOCOMMIT; the pooled connection must not stay that way."""
    sid, totals_before = await _started_session(file_db)
    await database.vacuum_database(bind=file_db.kw["bind"])

    ev = _llm_end()
    _fail_cost(monkeypatch)
    await main.process_single_event(ev, sid)

    assert await _event_rows(file_db, ev["event_id"]) == 0
    assert _totals(await _session(file_db, sid)) == totals_before


@pytest.mark.asyncio
async def test_new_event_and_aggregates_are_stored_and_broadcast(file_db, broadcasts):
    sid, (tokens, errors, agents) = await _started_session(file_db)
    broadcasts.clear()

    ev = _llm_end(status="error")
    await main.process_single_event(ev, sid)

    assert await _event_rows(file_db, ev["event_id"]) == 1
    sess = await _session(file_db, sid)
    assert _totals(sess) == (tokens + 30, errors + 1, agents + 1)
    assert sess.total_cost_usd == pytest.approx(0.000225)

    kinds = [kind for kind, _, _ in broadcasts]
    assert kinds == [
        "broadcast_to_session_ui",
        "broadcast_graph_update",
        "broadcast_session_update",
    ]
    session_update = broadcasts[-1][1][1]
    assert session_update["total_tokens"] == tokens + 30
    assert session_update["error_count"] == errors + 1


@pytest.fixture
def lookup_misses_once():
    """Make the first lookup of an event miss, as if another writer raced it.

    The insert then collides on the primary key inside the SAVEPOINT, which
    is the duplicate path that ``_persist_event`` recovers from.
    """
    state = {"event_id": None, "misses": 0}

    def on_execute(orm_execute_state):
        if state["event_id"] is None or state["misses"]:
            return
        stmt = orm_execute_state.statement
        if not orm_execute_state.is_select:
            return
        if EventModel.__table__ not in stmt.get_final_froms():
            return
        params = stmt.compile().params.values()
        if state["event_id"] in params:
            state["misses"] += 1
            orm_execute_state.statement = stmt.where(false())

    event.listen(Session, "do_orm_execute", on_execute)
    try:
        yield state
    finally:
        event.remove(Session, "do_orm_execute", on_execute)


@pytest.mark.asyncio
async def test_duplicate_insert_rolls_back_only_the_savepoint(
    file_db, broadcasts, lookup_misses_once
):
    sid, (tokens, errors, agents) = await _started_session(file_db)
    ev = _event(status="running")
    await main.process_single_event(ev, sid)
    broadcasts.clear()

    # Re-send the same event with a new status; its lookup misses, so the
    # INSERT collides and only the SAVEPOINT is rolled back before merging.
    lookup_misses_once["event_id"] = ev["event_id"]
    resent = dict(ev, status="error", latency_ms=42)
    await main.process_single_event(resent, sid)
    assert lookup_misses_once["misses"] == 1

    assert await _event_rows(file_db, ev["event_id"]) == 1
    async with file_db() as db:
        stored = await db.get(EventModel, ev["event_id"])
        assert (stored.status, stored.latency_ms) == ("error", 42)
    assert _totals(await _session(file_db, sid)) == (tokens, errors + 1, agents + 1)

    kinds = [kind for kind, _, _ in broadcasts]
    assert "broadcast_to_session_ui" in kinds
    assert broadcasts[-1][0] == "broadcast_session_update"
    assert broadcasts[-1][1][1]["error_count"] == errors + 1


@pytest.mark.asyncio
async def test_rejected_insert_does_not_change_aggregates(file_db, broadcasts, caplog):
    """An event the database rejects must not be counted in the session."""
    sid, totals_before = await _started_session(file_db)
    broadcasts.clear()

    # The parent does not exist, so the foreign key rejects the INSERT.
    ev = _event(status="error", parent_event_id=f"missing-{uuid.uuid4().hex}")
    with caplog.at_level(logging.INFO):
        await main.process_single_event(ev, sid)

    assert await _event_rows(file_db, ev["event_id"]) == 0
    assert _totals(await _session(file_db, sid)) == totals_before
    assert broadcasts == []

    failure = [
        r.getMessage() for r in caplog.records if ev["event_id"] in r.getMessage()
    ]
    assert len(failure) == 1, failure
    assert "FOREIGN KEY constraint failed" in failure[0]
