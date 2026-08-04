import pytest
from httpx import AsyncClient, ASGITransport

from main import app


@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


@pytest.mark.asyncio
async def test_session_lifecycle():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:

        # 1. Create a session
        create_res = await ac.post(
            "/api/sessions",
            json={
                "session_id": "test-session-123",
                "name": "Test Integration Run",
                "metadata": {"env": "test"},
            },
        )
        assert create_res.status_code == 201
        data = create_res.json()
        assert data["session_id"] == "test-session-123"
        assert data["status"] == "running"
        assert data["metadata"] == {"env": "test"}

        # 2. Get specific session
        get_res = await ac.get("/api/sessions/test-session-123")
        assert get_res.status_code == 200
        assert get_res.json()["name"] == "Test Integration Run"

        # 3. List all sessions
        list_res = await ac.get("/api/sessions")
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["total"] >= 1
        assert any(s["session_id"] == "test-session-123" for s in list_data["sessions"])

        # 4. Patch session state to completed
        patch_res = await ac.patch(
            "/api/sessions/test-session-123", json={"status": "completed"}
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["status"] == "completed"

        # 5. Delete session
        del_res = await ac.delete("/api/sessions/test-session-123")
        assert del_res.status_code == 204

        # 6. Verify 404 upon deletion
        get_res_deleted = await ac.get("/api/sessions/test-session-123")
        assert get_res_deleted.status_code == 404


def test_websocket_sdk_ingest():
    import uuid

    session_id = f"ws-test-session-{uuid.uuid4()}"
    ev_llm_id = f"ev-llm-{uuid.uuid4()}"
    ev_err_id = f"ev-err-{uuid.uuid4()}"

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        # 1. Initialize session via REST
        client.post(
            "/api/sessions",
            json={
                "session_id": session_id,
                "name": "WS Test Run",
                "metadata": {"env": "test-ws"},
            },
        )

        # 2. Stream events through the SDK WebSocket connection
        with client.websocket_connect("/ws?client_type=sdk") as websocket:
            # Event 1: LLM completed event (agent-alpha, 150 tokens)
            websocket.send_json(
                {
                    "type": "event",
                    "session_id": session_id,
                    "event": {
                        "event_id": ev_llm_id,
                        "event_type": "llm_end",
                        "agent_name": "agent-alpha",
                        "agent_type": "llm",
                        "status": "completed",
                        "timestamp": "2026-07-23T12:00:00.000Z",
                        "latency_ms": 150,
                        "payload": {
                            "model": "gpt-4o",
                            "prompt_tokens": 100,
                            "completion_tokens": 50,
                            "total_tokens": 150,
                        },
                    },
                }
            )
            # Event 2: Chain error event (agent-beta, status error)
            websocket.send_json(
                {
                    "type": "event",
                    "session_id": session_id,
                    "event": {
                        "event_id": ev_err_id,
                        "event_type": "chain_error",
                        "agent_name": "agent-beta",
                        "agent_type": "chain",
                        "status": "error",
                        "timestamp": "2026-07-23T12:00:05.000Z",
                        "latency_ms": 200,
                        "payload": {"error": "Division by zero"},
                    },
                }
            )
            import time

            for _ in range(30):
                response = client.get(f"/api/sessions/{session_id}")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("total_tokens") == 150:
                        break
                time.sleep(0.1)

        # 3. Retrieve session metrics via REST and verify updates
        response = client.get(f"/api/sessions/{session_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["total_tokens"] == 150
        assert data["error_count"] == 1
        assert data["agent_count"] == 2


def test_websocket_event_upsert_and_merge():
    import uuid
    import time
    from fastapi.testclient import TestClient

    session_id = f"upsert-test-session-{uuid.uuid4()}"
    run_id = f"run-llm-{uuid.uuid4()}"

    with TestClient(app) as client:
        # Create session
        client.post(
            "/api/sessions",
            json={
                "session_id": session_id,
                "name": "WS Upsert Test Run",
            },
        )

        with client.websocket_connect("/ws?client_type=sdk") as websocket:
            # 1. Send llm_start event
            websocket.send_json(
                {
                    "type": "event",
                    "session_id": session_id,
                    "event": {
                        "event_id": run_id,
                        "event_type": "llm_start",
                        "agent_name": "WriterAgent",
                        "agent_type": "llm",
                        "status": "running",
                        "timestamp": "2026-07-24T12:00:00.000Z",
                        "payload": {
                            "model": "gpt-4o",
                            "prompts": ["Draft a short story about antigravity."],
                            "streaming": False,
                        },
                    },
                }
            )
            # Check that database has the start event with correct fields (using bounded retry polling)
            res_start = None
            for _ in range(30):
                response = client.get(f"/api/sessions/{session_id}/events/{run_id}")
                if response.status_code == 200:
                    res_start = response
                    break
                time.sleep(0.1)

            assert res_start is not None, f"Start event {run_id} not found in database within timeout"
            assert res_start.status_code == 200
            start_data = res_start.json()
            assert start_data["event_type"] == "llm_start"
            assert start_data["status"] == "running"
            assert start_data["payload"]["model"] == "gpt-4o"
            assert start_data["payload"]["prompts"] == ["Draft a short story about antigravity."]

            # 2. Send llm_end event (model is empty, prompts is empty, completion is set)
            websocket.send_json(
                {
                    "type": "event",
                    "session_id": session_id,
                    "event": {
                        "event_id": run_id,
                        "event_type": "llm_end",
                        "agent_name": "WriterAgent",
                        "agent_type": "llm",
                        "status": "completed",
                        "timestamp": "2026-07-24T12:00:02.000Z",
                        "latency_ms": 2000,
                        "payload": {
                            "model": "",
                            "prompts": [],
                            "completion": "Once upon a time, weightlessness was discovered...",
                            "prompt_tokens": 10,
                            "completion_tokens": 20,
                            "total_tokens": 30,
                        },
                    },
                }
            )
            
            # Wait for websocket worker task to finish DB operations
            for _ in range(30):
                response = client.get(f"/api/sessions/{session_id}")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("total_tokens") == 30:
                        break
                time.sleep(0.1)

        # 3. Retrieve event and verify it was merged (not discarded)
        res_end = client.get(f"/api/sessions/{session_id}/events/{run_id}")
        assert res_end.status_code == 200
        end_data = res_end.json()
        assert end_data["event_type"] == "llm_end"
        assert end_data["status"] == "completed"
        assert end_data["latency_ms"] == 2000

        # Verify that start payload fields (model, prompts) were NOT overwritten by empty fields in end event!
        payload = end_data["payload"]
        assert payload["model"] == "gpt-4o"
        assert payload["prompts"] == ["Draft a short story about antigravity."]
        assert payload["completion"] == "Once upon a time, weightlessness was discovered..."
        assert payload["total_tokens"] == 30

        # Verify session aggregates are correct
        sess_res = client.get(f"/api/sessions/{session_id}")
        assert sess_res.status_code == 200
        sess_data = sess_res.json()
        assert sess_data["total_tokens"] == 30
        # gpt-4o price is 2.50 input / 10.00 output per 1M tokens
        # 10 input -> 10/1M * 2.50 = 0.000025
        # 20 output -> 20/1M * 10.00 = 0.0002
        # total cost = 0.000225
        assert abs(sess_data["total_cost_usd"] - 0.000225) < 1e-6


def test_set_sqlite_pragma_bypasses_non_sqlite():
    from unittest.mock import MagicMock
    from database import set_sqlite_pragma
    import database

    # Mock engine.dialect.name to "postgresql"
    original_engine = database.engine
    mock_engine = MagicMock()
    mock_engine.dialect.name = "postgresql"
    database.engine = mock_engine

    try:
        mock_conn = MagicMock()
        # Call set_sqlite_pragma hook
        set_sqlite_pragma(mock_conn, None)
        # Verify that cursor was never called on the connection (because it was skipped!)
        mock_conn.cursor.assert_not_called()
    finally:
        # Restore original engine
        database.engine = original_engine


def test_implicit_session_status_synchronization():
    import uuid
    import time
    from fastapi.testclient import TestClient

    session_id = f"status-sync-session-{uuid.uuid4()}"
    run_id = f"run-root-{uuid.uuid4()}"

    with TestClient(app) as client:
        # Create session
        client.post(
            "/api/sessions",
            json={
                "session_id": session_id,
                "name": "Root status sync test",
            },
        )

        # Verify that session is initially "running"
        res_sess = client.get(f"/api/sessions/{session_id}")
        assert res_sess.status_code == 200
        assert res_sess.json()["status"] == "running"
        assert res_sess.json()["ended_at"] is None

        with client.websocket_connect("/ws?client_type=sdk") as websocket:
            # Send root chain completed event (parent_event_id is None)
            websocket.send_json(
                {
                    "type": "event",
                    "session_id": session_id,
                    "event": {
                        "event_id": run_id,
                        "event_type": "chain_end",
                        "agent_name": "Chain",
                        "agent_type": "chain",
                        "status": "completed",
                        "timestamp": "2026-07-24T12:00:00.000Z",
                        "payload": {
                            "chain_type": "Chain",
                            "inputs": {},
                            "outputs": {},
                        },
                    },
                }
            )

            # Wait for websocket ingestion to process and implicitly update session status
            for _ in range(30):
                response = client.get(f"/api/sessions/{session_id}")
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "completed":
                        break
                time.sleep(0.1)

        # Check that session status has transitioned to "completed" and ended_at is set
        res_sess = client.get(f"/api/sessions/{session_id}")
        assert res_sess.status_code == 200
        sess_data = res_sess.json()
        assert sess_data["status"] == "completed"
        assert sess_data["ended_at"] is not None


def test_sdk_client_integration(db_engine):
    import uvicorn
    import threading
    import socket
    import time
    import uuid
    import urllib.request
    from agentscope.client import AgentScopeClient

    # Get a free port
    s = socket.socket()
    s.bind(("", 0))
    port = s.getsockname()[1]
    s.close()

    # Boot local server in background thread
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to be ready
    for _ in range(30):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=0.1
            ) as r:
                if r.status == 200:
                    break
        except Exception:
            pass
        time.sleep(0.05)

    client = AgentScopeClient(
        host="127.0.0.1", port=port, session_name="IntegrationTestSession"
    )
    try:
        # Start SDK client
        client.start()

        # Emit some events
        event_id = str(uuid.uuid4())
        client.emit(
            {
                "event_id": event_id,
                "event_type": "chain_start",
                "agent_name": "TestAgent",
                "agent_type": "custom",
                "status": "running",
                "payload": {"input": "test-data"},
            }
        )

        # Wait until session is created and the event is ingested
        session_id = None
        for _ in range(40):
            if client.session_id:
                session_id = client.session_id
                break
            time.sleep(0.1)

        assert session_id is not None, "SDK client failed to register session"

        # Verify via REST API that the event exists
        res_event = None
        from fastapi.testclient import TestClient

        with TestClient(app) as test_client:
            for _ in range(40):
                r = test_client.get(
                    f"/api/sessions/{session_id}/events/{event_id}"
                )
                if r.status_code == 200:
                    res_event = r.json()
                    break
                time.sleep(0.1)

        assert res_event is not None, "Event was not ingested by the server"
        assert res_event["event_type"] == "chain_start"
        assert res_event["payload"]["input"] == "test-data"

    finally:
        client.stop()
        server.should_exit = True
        thread.join(timeout=2.0)


@pytest.mark.asyncio
async def test_session_retention_pruning(db_session):
    import os
    import uuid
    from datetime import datetime, timedelta
    from models import SessionModel
    from main import prune_old_sessions
    from sqlalchemy import select, delete

    # Clear existing database sessions to ensure isolated counts
    await db_session.execute(delete(SessionModel))
    await db_session.commit()

    # Insert 1 old session (10 days ago) and 1 new session (now)
    old_id = f"old-{uuid.uuid4()}"
    new_id = f"new-{uuid.uuid4()}"

    old_sess = SessionModel(
        session_id=old_id,
        name="Old Session",
        status="completed",
        started_at=datetime.utcnow() - timedelta(days=10),
    )
    new_sess = SessionModel(
        session_id=new_id,
        name="New Session",
        status="completed",
        started_at=datetime.utcnow(),
    )

    db_session.add(old_sess)
    db_session.add(new_sess)
    await db_session.commit()

    # Trigger prune with RETENTION_DAYS = 5
    os.environ["RETENTION_DAYS"] = "5"
    try:
        await prune_old_sessions()

        # Verify old session is deleted, new session remains
        stmt = select(SessionModel).where(
            SessionModel.session_id.in_([old_id, new_id])
        )
        res = await db_session.execute(stmt)
        remaining = res.scalars().all()

        assert len(remaining) == 1
        assert remaining[0].session_id == new_id
    finally:
        if "RETENTION_DAYS" in os.environ:
            del os.environ["RETENTION_DAYS"]


@pytest.mark.asyncio
async def test_session_max_limit_pruning(db_session):
    import os
    import uuid
    from datetime import datetime, timedelta
    from models import SessionModel
    from main import prune_old_sessions
    from sqlalchemy import select, delete

    # Clear existing database sessions to ensure isolated counts
    await db_session.execute(delete(SessionModel))
    await db_session.commit()

    # Insert 4 sessions with different started_at times
    session_ids = []
    for i in range(4):
        sid = f"limit-{i}-{uuid.uuid4()}"
        sess = SessionModel(
            session_id=sid,
            name=f"Session {i}",
            status="completed",
            started_at=datetime.utcnow() - timedelta(minutes=10 - i),
        )
        db_session.add(sess)
        session_ids.append(sid)
    await db_session.commit()

    # Trigger prune with MAX_SESSIONS = 2
    os.environ["MAX_SESSIONS"] = "2"
    try:
        await prune_old_sessions()

        # Verify only the 2 newest sessions remain (limit-2 and limit-3)
        stmt = select(SessionModel).where(
            SessionModel.session_id.in_(session_ids)
        )
        res = await db_session.execute(stmt)
        remaining = res.scalars().all()

        assert len(remaining) == 2
        remaining_ids = {r.session_id for r in remaining}
        assert session_ids[2] in remaining_ids
        assert session_ids[3] in remaining_ids
    finally:
        if "MAX_SESSIONS" in os.environ:
            del os.environ["MAX_SESSIONS"]

def test_list_events_pagination():
    import uuid
    from fastapi.testclient import TestClient

    session_id = f"pagination-test-{uuid.uuid4()}"
    with TestClient(app) as client:
        # Create session
        client.post(
            "/api/sessions",
            json={
                "session_id": session_id,
                "name": "Pagination Test Run",
            },
        )

        with client.websocket_connect("/ws?client_type=sdk") as websocket:
            # Send 5 events
            for i in range(5):
                websocket.send_json(
                    {
                        "type": "event",
                        "session_id": session_id,
                        "event": {
                            "event_id": f"event-{i}-{uuid.uuid4()}",
                            "event_type": "chain_start",
                            "agent_name": f"agent-{i}",
                            "agent_type": "chain",
                            "status": "running",
                            "timestamp": f"2026-08-04T12:00:0{i}.000Z",
                            "payload": {"index": i},
                        },
                    }
                )

            # Wait for ingestion to complete
            import time

            for _ in range(30):
                # Retrieve first page with limit=2
                res = client.get(
                    f"/api/sessions/{session_id}/events?page=1&limit=2"
                )
                if res.status_code == 200 and res.json()["total_count"] == 5:
                    break
                time.sleep(0.1)

        # 1. Verify page 1 of limit 2
        res = client.get(f"/api/sessions/{session_id}/events?page=1&limit=2")
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] == 5
        assert len(data["events"]) == 2
        assert data["page"] == 1
        assert data["limit"] == 2
        assert data["total_pages"] == 3
        assert data["events"][0]["payload"]["index"] == 0
        assert data["events"][1]["payload"]["index"] == 1

        # 2. Verify page 2 of limit 2
        res = client.get(f"/api/sessions/{session_id}/events?page=2&limit=2")
        assert res.status_code == 200
        data = res.json()
        assert len(data["events"]) == 2
        assert data["page"] == 2
        assert data["events"][0]["payload"]["index"] == 2
        assert data["events"][1]["payload"]["index"] == 3

        # 3. Verify page 3 of limit 2 (last page, only 1 event)
        res = client.get(f"/api/sessions/{session_id}/events?page=3&limit=2")
        assert res.status_code == 200
        data = res.json()
        assert len(data["events"]) == 1
        assert data["page"] == 3
        assert data["events"][0]["payload"]["index"] == 4

        # 4. Verify filters with pagination
        res = client.get(
            f"/api/sessions/{session_id}/events?page=1&limit=2&agent=agent-2"
        )
        assert res.status_code == 200
        data = res.json()
        assert data["total_count"] == 1
        assert len(data["events"]) == 1
        assert data["total_pages"] == 1
def test_server_pricing():
    from pricing import calculate_cost, get_model_pricing

    # Model configuration check
    prices = get_model_pricing("gpt-4o")
    assert prices is not None
    assert prices["input"] == 2.50
    assert prices["output"] == 10.00

    # gpt-4o-mini explicit pricing
    mini_prices = get_model_pricing("gpt-4o-mini")
    assert mini_prices["input"] == 0.15
    assert mini_prices["output"] == 0.60

    # gpt-4-turbo explicit pricing
    turbo_prices = get_model_pricing("gpt-4-turbo")
    assert turbo_prices["input"] == 10.00
    assert turbo_prices["output"] == 30.00

    # Prefix match checks
    assert get_model_pricing("gpt-4o-2024-05-13") == prices
    assert get_model_pricing("gpt-4o-mini-2024-07-18") == mini_prices
    assert get_model_pricing("gpt-4orange") is None

    # Calculate cost checks
    assert calculate_cost("gpt-4o", 1000, 2000) == (
        (1000 / 1_000_000 * 2.50) + (2000 / 1_000_000 * 10.00)
    )

    assert calculate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == (
        (1_000_000 / 1_000_000 * 0.15) + (1_000_000 / 1_000_000 * 0.60)
    )

    assert calculate_cost("unknown-model", 100, 100) == 0.0

    with pytest.raises(ValueError, match="prompt_tokens cannot be negative"):
        calculate_cost("gpt-4o", -1, 100)





