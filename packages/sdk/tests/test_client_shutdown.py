"""Shutdown behaviour of AgentScopeClient (#289, #294).

In-process tests replace websockets.connect with a recording fake; subprocess
tests run real interpreters to prove the process exits and buffered events
are delivered, with and without an explicit stop().
"""

import gc
import json
import os
import socket
import subprocess
import sys
import textwrap
import threading
import time
import weakref

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


def test_idle_sender_delivers_new_events_promptly(monkeypatch):
    """The sender must not poll: an event emitted while idle goes out at once."""
    received, arrivals = [], {}
    _fake_network(monkeypatch, _register_instantly, received, arrivals)
    client = AgentScopeClient()  # default flush_interval_seconds=0.1
    client.emit({"event_id": "warm"})
    assert _wait_until(lambda: "warm" in arrivals, 3.0)

    delays = []
    for i in range(10):
        # Idle for longer than the 0.1 s flush interval, at varying phases, so
        # a polling sender would add 0-100 ms to these events.
        time.sleep(0.12 + 0.017 * i)
        event_id = f"e{i}"
        emitted = time.perf_counter()
        client.emit({"event_id": event_id})
        assert _wait_until(lambda: event_id in arrivals, 2.0)
        delays.append(arrivals[event_id] - emitted)
    client.stop()

    shown = [round(d * 1000, 1) for d in delays]
    assert sorted(delays)[len(delays) // 2] < 0.015, shown
    assert max(delays) < 0.05, shown


def test_stop_wakes_a_reconnect_backoff(monkeypatch):
    """stop() must not wait out a long backoff (it can reach 30 s)."""
    received = []
    attempts = []

    def flaky_create(self):
        attempts.append(time.monotonic())
        if len(attempts) > 1:  # the server is back after the first failure
            self.session_id = "sess-1"

    _fake_network(monkeypatch, flaky_create, received)
    client = AgentScopeClient()
    client._initial_backoff = 30.0
    client.emit({"event_id": "a"})
    assert _wait_until(lambda: attempts, 2.0)
    time.sleep(0.1)  # now sleeping in the 30 s backoff

    returned, elapsed = _run_stop(client, timeout=3.0)

    assert returned
    assert elapsed < 0.5
    assert [e["event_id"] for e in received] == ["a"]


def test_restart_after_timed_out_stop_never_runs_two_senders(monkeypatch):
    received = []
    release = threading.Event()
    calls = []

    def slow_create(self):
        calls.append(1)
        if len(calls) == 1:
            release.wait(5)  # registration hangs past stop()'s timeout
        self.session_id = "sess-1"

    _fake_network(monkeypatch, slow_create, received)
    client = AgentScopeClient()
    client.emit({"event_id": "a"})
    first = client.thread
    client.stop(timeout=0.1)

    assert first.is_alive()
    assert client.running, "reported stopped while its sender thread still runs"
    client.emit({"event_id": "b"})
    assert client.thread is first, "a second sender thread was started"

    release.set()
    first.join(3)
    assert not first.is_alive()
    assert client.running is False

    client.emit({"event_id": "c"})  # a fresh sender picks everything up
    assert client.thread is not first
    assert _run_stop(client, 2.0)[0]
    assert [e["event_id"] for e in received] == ["a", "b", "c"]


def test_stopped_clients_are_garbage_collected(monkeypatch):
    """The exit hook must not keep every client ever started alive."""
    _fake_network(monkeypatch, _register_instantly, [])
    refs = []
    for i in range(50):
        client = AgentScopeClient()
        client.emit({"event_id": str(i)})
        client.stop(timeout=2.0)
        assert not client.running
        refs.append(weakref.ref(client))
        del client
    gc.collect()
    alive = sum(ref() is not None for ref in refs)
    assert alive == 0, f"{alive} of 50 stopped clients are still referenced"


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


def test_process_exit_stops_clients_in_parallel():
    """Each unreachable client may use its whole shutdown_timeout, but the
    clients are flushed in parallel, not one after another."""
    proc, elapsed = run_script(
        f"""
        clients = [
            AgentScopeClient(host="127.0.0.1", port={_unused_port()},
                             shutdown_timeout=1.5)
            for _ in range(3)
        ]
        for c in clients:
            c.emit({{"event_id": "x"}})
        print("BODY DONE", flush=True)
        """,
        fake=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "BODY DONE" in proc.stdout
    assert elapsed < 3.5, f"exit took {elapsed:.1f}s (3 x 1.5 s serially?)"
