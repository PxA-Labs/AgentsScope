"""Regression tests for AgentScopeClient.stop() (#289)."""

import queue
import threading
import time

from agentscope.client import AgentScopeClient


def _run_stop(client, timeout=5.0):
    t = threading.Thread(target=client.stop, daemon=True)
    started = time.monotonic()
    t.start()
    t.join(timeout)
    return not t.is_alive(), time.monotonic() - started


def test_stop_returns_when_buffer_full_and_server_unreachable():
    client = AgentScopeClient(host="127.0.0.1", port=1)  # nothing listening
    for i in range(client.queue.maxsize + 100):
        client.emit({"event_id": str(i)})
    assert client.queue.full()

    returned, elapsed = _run_stop(client)

    assert returned, "stop() deadlocked on a full buffer"
    assert elapsed < 4.0
    assert client.running is False
    # The sentinel made it in by evicting the oldest event.
    items = []
    while True:
        try:
            items.append(client.queue.get_nowait())
        except queue.Empty:
            break
    assert items[-1] is None
    assert len(items) == client.queue.maxsize


def test_stop_does_not_drop_events_when_sender_is_draining():
    client = AgentScopeClient()
    client.queue = queue.Queue(maxsize=3)
    client.running = True  # simulate a connected client without a real socket
    for i in range(3):
        client.queue.put({"event_id": f"e{i}"})

    received = []

    def sender():
        time.sleep(0.1)  # the sender frees space shortly after stop() starts
        while True:
            item = client.queue.get()
            received.append(item)
            if item is None:
                return

    t = threading.Thread(target=sender, daemon=True)
    t.start()
    returned, _ = _run_stop(client)
    t.join(2)

    assert returned
    assert received == [
        {"event_id": "e0"},
        {"event_id": "e1"},
        {"event_id": "e2"},
        None,
    ]


def test_stop_is_idempotent():
    client = AgentScopeClient(host="127.0.0.1", port=1)
    client.emit({"event_id": "x"})
    assert _run_stop(client)[0]
    assert _run_stop(client)[0]
