"""Bounded in-memory buffer semantics of AgentScopeClient."""

from agentscope.client import AgentScopeClient


def _event(i: int) -> dict:
    return {"event_id": f"e{i}", "event_type": "tool_end"}


def test_default_buffer_size_is_5000():
    client = AgentScopeClient()
    assert client.max_queue_size == 5000
    assert client.queue.maxsize == 5000


def test_buffer_size_is_configurable_and_clamped():
    assert AgentScopeClient(max_queue_size=10).queue.maxsize == 10
    assert AgentScopeClient(max_queue_size=0).queue.maxsize == 1


def test_full_buffer_drops_oldest_events_without_blocking(monkeypatch):
    client = AgentScopeClient(max_queue_size=3)
    # Keep the background sender from draining the queue.
    monkeypatch.setattr(client, "start", lambda: None)
    for i in range(5):
        client.emit(_event(i))
    remaining = [client.queue.get_nowait()["event_id"] for _ in range(3)]
    assert remaining == ["e2", "e3", "e4"]
    assert client.queue.empty()
