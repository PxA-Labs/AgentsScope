from agentscope.client import AgentScopeClient


def test_client_batching_configuration():
    client = AgentScopeClient(
        batch_size=25,
        flush_interval_seconds=0.05,
        session_name="Batching Test Session",
    )
    assert client.batch_size == 25
    assert client.flush_interval_seconds == 0.05
    assert client.session_name == "Batching Test Session"

    # Test emitting multiple events into queue
    for i in range(10):
        client.emit(
            {
                "event_id": f"event_{i}",
                "event_type": "chain_start",
                "agent_name": "TestAgent",
                "agent_type": "chain",
                "status": "running",
                "timestamp": "2026-08-23T00:00:00Z",
            }
        )

    assert client.queue.qsize() == 10

    # Stop client cleanly
    client.stop()
    assert not client.running
