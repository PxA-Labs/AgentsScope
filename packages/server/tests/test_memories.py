import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport
from main import app

@pytest.fixture
def mock_mem0_client():
    with patch("routers.memories.get_mem0_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        yield mock_client

@pytest.mark.asyncio
async def test_memories_api(mock_mem0_client):
    session_id = "test-mem-session"
    
    # 1. Test get_all
    mock_mem0_client.get_all.return_value = {
        "count": 1,
        "results": [{"id": "mem-1", "memory": "test memory text", "user_id": session_id}]
    }
    
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        res = await ac.get(f"/api/sessions/{session_id}/memories")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert data["results"][0]["id"] == "mem-1"
        mock_mem0_client.get_all.assert_called_once_with(filters={"user_id": session_id})
        
    # 2. Test add
    mock_mem0_client.add.return_value = {"event_id": "evt-123", "status": "PENDING"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        res = await ac.post(
            f"/api/sessions/{session_id}/memories",
            json={"text": "User likes programming", "metadata": {"tag": "code"}}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["event_id"] == "evt-123"
        mock_mem0_client.add.assert_called_once_with(
            "User likes programming", user_id=session_id, metadata={"tag": "code"}
        )
        
    # 3. Test search
    mock_mem0_client.search.return_value = {"results": [{"id": "mem-2", "memory": "relevant memory"}]}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        res = await ac.post(
            f"/api/sessions/{session_id}/memories/search",
            json={"query": "programming"}
        )
        assert res.status_code == 200
        data = res.json()
        assert len(data["results"]) == 1
        mock_mem0_client.search.assert_called_once_with(
            "programming", filters={"user_id": session_id}
        )
        
    # 4. Test delete
    mock_mem0_client.delete.return_value = {"message": "Deleted"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        res = await ac.delete(f"/api/sessions/{session_id}/memories/mem-1")
        assert res.status_code == 200
        data = res.json()
        assert data["message"] == "Deleted"
        mock_mem0_client.delete.assert_called_once_with("mem-1")
