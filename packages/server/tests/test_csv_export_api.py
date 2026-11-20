"""HTTP-level tests for GET /api/sessions/{id}/export?format=csv."""

import asyncio
import csv
import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from database import get_db
from httpx import ASGITransport, AsyncClient
from main import app
from models import EventModel, SessionModel
from pricing import calculate_cost
from sqlalchemy.ext.asyncio import AsyncSession


def recent_start() -> datetime:
    # Relative to now: the test database is shared across the run, and a fixed
    # date would age into test_retention's prune window and break its counts.
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    return now - timedelta(hours=1)


async def seed_session(db: AsyncSession, name: str = "CSV Run", n_events: int = 0):
    sess_id = str(uuid.uuid4())
    start = recent_start()
    db.add(
        SessionModel(
            session_id=sess_id,
            name=name,
            status="completed",
            started_at=start,
            total_tokens=0,
            total_cost_usd=0.0,
            metadata_={},
        )
    )
    root_id = f"{sess_id}-root"
    db.add(
        EventModel(
            event_id=root_id,
            session_id=sess_id,
            parent_event_id=None,
            event_type="chain_end",
            agent_name="Planner",
            agent_type="chain",
            timestamp=start,
            latency_ms=1200,
            status="completed",
            payload={"chain_type": "Planner", "inputs": {"q": "hi"}},
        )
    )
    db.add(
        EventModel(
            event_id=f"{sess_id}-llm",
            session_id=sess_id,
            parent_event_id=root_id,
            event_type="llm_end",
            agent_name="ChatOpenAI",
            agent_type="llm",
            timestamp=start + timedelta(seconds=1),
            latency_ms=800,
            status="completed",
            payload={
                "model": "gpt-4o",
                "prompts": ['Summarise:\nline 1, with comma\nline "2"'],
                "completion": "Done",
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
                "streaming": False,
            },
        )
    )
    db.add(
        EventModel(
            event_id=f"{sess_id}-tool",
            session_id=sess_id,
            parent_event_id=root_id,
            event_type="tool_error",
            agent_name='=HYPERLINK("http://evil")',
            agent_type="tool",
            timestamp=start + timedelta(seconds=2),
            latency_ms=None,
            status="error",
            payload={"tool_name": "search", "input": "x", "error": "Timeout"},
        )
    )
    for i in range(n_events):
        db.add(
            EventModel(
                event_id=f"{sess_id}-bulk-{i:05d}",
                session_id=sess_id,
                parent_event_id=root_id,
                event_type="tool_end",
                agent_name="bulk",
                agent_type="tool",
                timestamp=start + timedelta(seconds=3 + i),
                latency_ms=i,
                status="completed",
                payload={"tool_name": "bulk", "input": str(i), "output": "ok"},
            )
        )
    await db.commit()
    return sess_id


def parse_csv(text: str):
    assert text.startswith("\ufeff"), "CSV must start with a UTF-8 BOM"
    return list(csv.DictReader(io.StringIO(text[1:])))


@pytest.mark.asyncio
async def test_csv_export_returns_one_row_per_event(db_session: AsyncSession):
    sess_id = await seed_session(db_session, name="CSV Run")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/sessions/{sess_id}/export?format=csv")

    assert res.status_code == 200
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert res.headers["content-disposition"] == (
        f'attachment; filename="CSV_Run_{sess_id[:8]}.csv"'
    )

    rows = parse_csv(res.text)
    assert [r["event_type"] for r in rows] == ["chain_end", "llm_end", "tool_error"]

    root, llm, tool = rows
    assert root["parent_event_id"] == ""
    assert llm["parent_event_id"] == root["event_id"]
    assert llm["model"] == "gpt-4o"
    assert (llm["prompt_tokens"], llm["completion_tokens"], llm["total_tokens"]) == (
        "120",
        "30",
        "150",
    )
    assert float(llm["cost_usd"]) == pytest.approx(calculate_cost("gpt-4o", 120, 30))
    assert json.loads(llm["payload_json"])["prompts"][0].endswith('line "2"')

    assert tool["tool_name"] == "search"
    assert tool["error"] == "Timeout"
    assert tool["status"] == "error"
    assert tool["latency_ms"] == ""
    # Formula injection is neutralised.
    assert tool["agent_name"] == '\'=HYPERLINK("http://evil")'


@pytest.mark.asyncio
async def test_json_remains_the_default_export_format(db_session: AsyncSession):
    sess_id = await seed_session(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        default = await client.get(f"/api/sessions/{sess_id}/export")
        explicit = await client.get(f"/api/sessions/{sess_id}/export?format=json")

    for res in (default, explicit):
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("application/json")
        assert len(res.json()["events"]) == 3


@pytest.mark.asyncio
async def test_csv_export_errors(db_session: AsyncSession):
    sess_id = await seed_session(db_session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get("/api/sessions/does-not-exist/export?format=csv")
        bad_format = await client.get(f"/api/sessions/{sess_id}/export?format=xlsx")

    assert missing.status_code == 404
    assert bad_format.status_code == 422


@pytest.mark.asyncio
async def test_csv_export_of_session_without_events_has_only_header(
    db_session: AsyncSession,
):
    sess_id = str(uuid.uuid4())
    db_session.add(
        SessionModel(
            session_id=sess_id,
            name="empty",
            status="running",
            started_at=recent_start(),
            metadata_={},
        )
    )
    await db_session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get(f"/api/sessions/{sess_id}/export?format=csv")
    assert res.status_code == 200
    assert parse_csv(res.text) == []


async def asgi_get(path: str, query: str = "", log: list | None = None):
    """Call the ASGI app directly and return the raw response messages.

    httpx's ASGITransport buffers the whole body, so it cannot show whether a
    response was streamed; the raw ``http.response.body`` messages can.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"host", b"test")],
        "client": ("127.0.0.1", 12345),
        "server": ("test", 80),
    }
    messages = []
    request_sent = False
    disconnected = asyncio.Event()

    async def receive():
        # First call delivers the (empty) request body. Later calls come from
        # Starlette's disconnect listener and must block like a real server
        # would until the client goes away, instead of busy-looping.
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if log is not None:
            log.append(("send", message["type"]))

    await app(scope, receive, send)
    return messages


@pytest.mark.asyncio
async def test_large_csv_export_streams_with_real_db_dependency(
    db_session: AsyncSession,
):
    """Use the real get_db dependency (not the test override) to prove the
    database session stays open for the whole streamed response, across
    several yield_per batches, and that the body is sent incrementally.

    AsyncSession silently reconnects after close(), so reading rows alone
    cannot show that the session was closed early. Instead get_db is wrapped
    to log every session.close() and its own teardown, interleaved with the
    ASGI messages, and both must come after the last body message.
    """
    n_bulk = 1200  # > 2 batches of CSV_EXPORT_BATCH_SIZE (500)
    sess_id = await seed_session(db_session, n_events=n_bulk)

    log = []

    async def tracked_get_db():
        async for session in get_db():
            real_close = session.close

            async def close():
                log.append(("db", "close"))
                await real_close()

            session.close = close
            try:
                yield session
            finally:
                log.append(("db", "get_db finally"))

    app.dependency_overrides[get_db] = tracked_get_db
    messages = await asgi_get(f"/api/sessions/{sess_id}/export", "format=csv", log)

    start, *bodies = messages
    assert start["type"] == "http.response.start"
    assert start["status"] == 200
    body_chunks = [m["body"] for m in bodies if m["body"]]
    # One message per CSV line: the body is streamed, not built in memory.
    assert len(body_chunks) == n_bulk + 3 + 1  # rows + header
    assert all(m.get("more_body") for m in bodies[:-1])
    assert bodies[-1].get("more_body", False) is False

    last_body = max(i for i, e in enumerate(log) if e == ("send", "http.response.body"))
    db_entries = [i for i, e in enumerate(log) if e[0] == "db"]
    assert ("db", "get_db finally") in log
    assert ("db", "close") in log
    assert min(db_entries) > last_body, f"session closed mid-response: {log[:5]}"

    rows = parse_csv(b"".join(body_chunks).decode("utf-8"))
    assert len(rows) == n_bulk + 3
    bulk = [r for r in rows if r["agent_name"] == "bulk"]
    assert [int(r["latency_ms"]) for r in bulk] == list(range(n_bulk))
