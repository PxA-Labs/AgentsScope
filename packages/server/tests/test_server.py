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
