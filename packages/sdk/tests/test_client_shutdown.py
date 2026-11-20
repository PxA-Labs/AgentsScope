"""Shutdown behaviour of AgentScopeClient (#289, #294).

In-process tests replace websockets.connect with a recording fake; subprocess
tests run real interpreters to prove the process exits and buffered events
are delivered, with and without an explicit stop().
"""

import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time

import pytest

from agentscope.client import AgentScopeClient

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class FakeWebSocket:
    def __init__(self, sink, delay=0.0, arrivals=None):
        self.sink = sink
        self.delay = delay
        self.arrivals = arrivals

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def send(self, raw):
        if self.delay:
            import asyncio

            await asyncio.sleep(self.delay)
        message = json.loads(raw)
        events = message.get("events") or [message.get("event")]
        self.sink.extend(events)
        if self.arrivals is not None:
            now = time.perf_counter()
            for event in events:
                self.arrivals.setdefault(event["event_id"], now)


def _fake_network(monkeypatch, create, received, arrivals=None):
    monkeypatch.setattr(AgentScopeClient, "_create_session_sync", create)
    monkeypatch.setattr(
        "agentscope.client.websockets.connect",
        lambda uri, **kwargs: FakeWebSocket(received, arrivals=arrivals),
    )


def _register_instantly(self):
    self.session_id = "sess-1"


def _wait_until(predicate, timeout):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.002)
    return True


@pytest.fixture
def fake_server(monkeypatch):
    """Patch session creation and the WebSocket; return the received events."""
    received = []

    def fake_create(self):
        time.sleep(0.2)  # registration takes a moment, as over a real network
        self.session_id = "sess-1"

    monkeypatch.setattr(AgentScopeClient, "_create_session_sync", fake_create)
    monkeypatch.setattr(
        "agentscope.client.websockets.connect",
        lambda uri, **kwargs: FakeWebSocket(received),
    )
    return received


def _unused_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_stop(client, timeout):
    t = threading.Thread(target=client.stop, kwargs={"timeout": timeout}, daemon=True)
    started = time.monotonic()
    t.start()
    t.join(timeout + 5)
    return not t.is_alive(), time.monotonic() - started


def test_stop_delivers_events_emitted_before_registration(fake_server):
    client = AgentScopeClient()
    for i in range(120):
        client.emit({"event_id": f"e{i}"})
    # stop() right away: the session is not registered yet (takes 0.2 s).
    returned, elapsed = _run_stop(client, timeout=3.0)
    assert returned and elapsed < 3.0
    assert [e["event_id"] for e in fake_server] == [f"e{i}" for i in range(120)]
    assert client.running is False


def test_stop_is_bounded_when_server_unreachable():
    client = AgentScopeClient(host="127.0.0.1", port=_unused_port())
    for i in range(10):
        client.emit({"event_id": str(i)})
    returned, elapsed = _run_stop(client, timeout=1.0)
    assert returned
    assert elapsed < 2.5


def test_stop_returns_when_buffer_full_and_server_unreachable():
    """Regression for #289: stop() used to block forever on a full buffer."""
    client = AgentScopeClient(host="127.0.0.1", port=_unused_port())
    for i in range(client.queue.maxsize + 100):
        client.emit({"event_id": str(i)})
    assert client.queue.full()
    returned, elapsed = _run_stop(client, timeout=1.0)
    assert returned, "stop() deadlocked on a full buffer"
    assert elapsed < 2.5
    assert client.running is False


def test_stop_is_idempotent_and_client_can_restart(fake_server):
    client = AgentScopeClient()
    client.emit({"event_id": "a"})
    assert _run_stop(client, 2.0)[0]
    assert _run_stop(client, 2.0)[0]
    client.emit({"event_id": "b"})  # restarts the background thread
    assert _run_stop(client, 2.0)[0]
    assert [e["event_id"] for e in fake_server] == ["a", "b"]


# --- real interpreters -----------------------------------------------------

SCRIPT_PRELUDE = """
import atexit, json, sys, time
sys.path.insert(0, {sdk_dir!r})
import agentscope.client as client_module
from agentscope.client import AgentScopeClient

received = []

class FakeWebSocket:
    async def __aenter__(self): return self
    async def __aexit__(self, *exc): return False
    async def send(self, raw):
        message = json.loads(raw)
        received.extend(message.get("events") or [message.get("event")])

def fake_create(self):
    time.sleep(0.2)
    self.session_id = "sess-1"

if {fake!r}:
    AgentScopeClient._create_session_sync = fake_create
    client_module.websockets.connect = lambda uri, **kw: FakeWebSocket()

# Registered before the client's own atexit hook, so it runs after it (LIFO)
# and reports what was delivered by the time the interpreter shuts down.
atexit.register(lambda: print("DELIVERED", len(received), flush=True))
"""


def run_script(body, fake=True, timeout=20):
    code = textwrap.dedent(SCRIPT_PRELUDE.format(sdk_dir=SDK_DIR, fake=fake)) + (
        textwrap.dedent(body)
    )
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc, time.monotonic() - started


def test_process_exits_and_delivers_without_explicit_stop():
    """Regression for #294: a connected process never exited."""
    proc, elapsed = run_script("""
        from agentscope.decorators import configure, trace
        configure(session_name="exit-test")

        @trace(name="step")
        def step(i):
            return i

        for i in range(25):
            step(i)
        time.sleep(0.5)  # let the sender connect, so the old code would hang
        print("BODY DONE", flush=True)
        """)
    assert proc.returncode == 0, proc.stderr
    assert "BODY DONE" in proc.stdout
    # @trace sends a start and an end event per call (same event_id).
    assert "DELIVERED 50" in proc.stdout
    assert elapsed < 10


def test_process_with_immediate_stop_delivers_everything():
    proc, _ = run_script("""
        client = AgentScopeClient(session_name="stop-test")
        for i in range(40):
            client.emit({"event_id": str(i)})
        client.stop(timeout=3.0)
        print("STOPPED", flush=True)
        """)
    assert proc.returncode == 0, proc.stderr
    assert "STOPPED" in proc.stdout
    assert "DELIVERED 40" in proc.stdout


def test_process_exits_promptly_when_server_unreachable():
    proc, elapsed = run_script(
        f"""
        client = AgentScopeClient(host="127.0.0.1", port={_unused_port()},
                                  shutdown_timeout=1.0)
        for i in range(10):
            client.emit({{"event_id": str(i)}})
        print("BODY DONE", flush=True)
        """,
        fake=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "BODY DONE" in proc.stdout
    assert "DELIVERED 0" in proc.stdout
    assert elapsed < 8


def test_short_script_without_stop_or_sleep_delivers_and_exits_fast():
    """A script that ends right after its last event (no sleep, no stop()).

    CPython shuts down concurrent.futures before atexit hooks run, so the
    flush at exit cannot rely on the default executor.
    """
    proc, elapsed = run_script("""
        from agentscope.decorators import configure, trace
        configure(session_name="short-script")

        @trace(name="step")
        def step(i):
            return i

        for i in range(30):
            step(i)
        """)
    assert proc.returncode == 0, proc.stderr
    assert "DELIVERED 60" in proc.stdout, proc.stdout + proc.stderr
    assert elapsed < 3, f"exit took {elapsed:.1f}s"
