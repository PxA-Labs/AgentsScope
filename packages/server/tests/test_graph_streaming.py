import json
from datetime import datetime, timezone
from types import SimpleNamespace

import graph_layout
import main
import pytest
from graph_layout import build_incremental_graph_update
from ws_manager import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.sent = []

    async def accept(self):
        pass

    async def send_text(self, text):
        self.sent.append(json.loads(text))


def _event(**overrides):
    fields = {
        "event_id": "child",
        "parent_event_id": "root",
        "event_type": "tool_end",
        "agent_name": "calculator",
        "agent_type": "tool",
        "latency_ms": 12,
        "status": "completed",
        "payload": {"total_tokens": 7},
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_build_incremental_graph_update_node_and_edge():
    node, edge = build_incremental_graph_update(_event())

    assert node["id"] == "child"
    assert node["type"] == "ToolNode"
    assert node["data"]["tokenCount"] == 7
    assert node["data"]["durationMs"] == 12
    assert edge == {
        "id": "e-root-child",
        "source": "root",
        "target": "child",
        "type": "default",
    }


def test_build_incremental_graph_update_root_has_no_edge():
    node, edge = build_incremental_graph_update(
        _event(event_id="root", parent_event_id=None, agent_type="chain")
    )
    assert node["type"] == "ChainNode"
    assert edge is None


@pytest.mark.asyncio
async def test_graph_updates_are_scoped_to_session_subscribers():
    manager = ConnectionManager()
    session_ws, other_ws, global_ws = FakeWebSocket(), FakeWebSocket(), FakeWebSocket()
    await manager.connect_ui(session_ws, "sess-1")
    await manager.connect_ui(other_ws, "sess-2")
    await manager.connect_ui(global_ws)

    node, edge = build_incremental_graph_update(_event())
    await manager.broadcast_graph_update("sess-1", node=node, edge=edge)
    await manager.broadcast_to_session_ui("sess-1", {"type": "event"})

    assert [m["type"] for m in session_ws.sent] == ["graph_update", "event"]
    assert session_ws.sent[0] == {
        "type": "graph_update",
        "session_id": "sess-1",
        "node": node,
        "edge": edge,
    }
    assert other_ws.sent == []
    assert global_ws.sent == []


@pytest.mark.asyncio
async def test_event_ingest_streams_incremental_node_without_full_layout(
    db_engine, monkeypatch
):
    broadcasts = []

    async def record_graph_update(session_id, node, edge):
        broadcasts.append((session_id, node, edge))

    def fail_full_layout(*args, **kwargs):
        raise AssertionError("full graph layout must not be recomputed per event")

    monkeypatch.setattr(main.manager, "broadcast_graph_update", record_graph_update)
    monkeypatch.setattr(graph_layout, "compute_graph_layout", fail_full_layout)

    await main.process_single_event(
        {
            "event_id": "stream-evt-1",
            "event_type": "chain_start",
            "agent_name": "Pipeline",
            "agent_type": "chain",
            "status": "running",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": {},
        },
        "graph-stream-session",
    )

    assert len(broadcasts) == 1
    session_id, node, edge = broadcasts[0]
    assert session_id == "graph-stream-session"
    assert node["id"] == "stream-evt-1"
    assert node["type"] == "ChainNode"
    assert edge is None
