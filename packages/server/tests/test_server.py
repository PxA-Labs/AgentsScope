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
