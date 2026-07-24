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


