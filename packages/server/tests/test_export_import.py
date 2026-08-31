import uuid
from datetime import datetime, timezone

import pytest
from database import get_db
from httpx import ASGITransport, AsyncClient
from main import app
from models import EventModel, SessionModel
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_session_export_and_import(db_session: AsyncSession):
    # 1. Seed a session with events
    sess_id = str(uuid.uuid4())
    event_id1 = str(uuid.uuid4())
    event_id2 = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    db_sess = SessionModel(
        session_id=sess_id,
        name="Test Pipeline Run",
        status="completed",
        started_at=now,
        ended_at=now,
        total_tokens=150,
        total_cost_usd=0.0045,
        error_count=0,
        agent_count=2,
        metadata_={"environment": "testing"},
    )
    db_session.add(db_sess)

    ev1 = EventModel(
        event_id=event_id1,
        session_id=sess_id,
        parent_event_id=None,
        event_type="chain_start",
        agent_name="RouterAgent",
        agent_type="chain",
        timestamp=now,
        latency_ms=None,
        status="completed",
        payload={"inputs": {"query": "Hello"}},
    )
    ev2 = EventModel(
        event_id=event_id2,
        session_id=sess_id,
        parent_event_id=event_id1,
        event_type="llm_end",
        agent_name="OpenAI_GPT4",
        agent_type="llm",
        timestamp=now,
        latency_ms=350,
        status="completed",
        payload={
            "model": "gpt-4o",
            "prompts": ["User: Hello"],
            "total_tokens": 150,
            "prompt_tokens": 50,
            "completion_tokens": 100,
        },
    )
    db_session.add_all([ev1, ev2])
    await db_session.commit()

    # 2. Test Export Endpoint
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        app.dependency_overrides[get_db] = lambda: db_session

        res = await client.get(f"/api/sessions/{sess_id}/export")
        assert res.status_code == 200
        export_data = res.json()

        assert export_data["version"] == "1.0"
        assert "exported_at" in export_data
        assert export_data["session"]["session_id"] == sess_id
        assert export_data["session"]["name"] == "Test Pipeline Run"
        assert len(export_data["events"]) == 2
        assert export_data["events"][0]["event_id"] == event_id1
        assert export_data["events"][1]["event_id"] == event_id2

        # Test Export 404 for non-existent session
        res_404 = await client.get("/api/sessions/non-existent-id/export")
        assert res_404.status_code == 404

        # 3. Test Import Endpoint with distinct session_id
        new_sess_id = str(uuid.uuid4())
        export_data["session"]["session_id"] = new_sess_id
        export_data["session"]["name"] = "Imported Pipeline Run"
        export_data["events"][0]["session_id"] = new_sess_id
        export_data["events"][1]["session_id"] = new_sess_id

        import_res = await client.post("/api/sessions/import", json=export_data)
        assert import_res.status_code == 201
        imported_resp = import_res.json()
        assert imported_resp["session_id"] == new_sess_id
        assert imported_resp["name"] == "Imported Pipeline Run"
        assert imported_resp["total_tokens"] == 150

        # Verify imported session can be fetched
        fetch_res = await client.get(f"/api/sessions/{new_sess_id}")
        assert fetch_res.status_code == 200

        # Verify imported events exist
        events_res = await client.get(f"/api/sessions/{new_sess_id}/events")
        assert events_res.status_code == 200
        assert len(events_res.json()["events"]) == 2

        # 4. Test Import with Collision (should disambiguate ID)
        reimport_res = await client.post("/api/sessions/import", json=export_data)
        assert reimport_res.status_code == 201
        reimported_resp = reimport_res.json()
        assert reimported_resp["session_id"] != new_sess_id
        assert "imported" in reimported_resp["session_id"]
        assert "Imported" in reimported_resp["name"]

        app.dependency_overrides.clear()
