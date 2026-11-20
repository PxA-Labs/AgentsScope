"""End-to-end SDK shutdown against a real uvicorn server (#294).

Runs the SDK in separate interpreters, so the test observes exactly what a
user's script does: whether it exits and what reaches the database.
"""

import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
import uuid

import pytest

SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def _uvicorn(extra_env=None):
    """Run the real server in its own process; stop it by its PID."""
    port = _free_port()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/e2e.db"}
        env.pop("AGENTSCOPE_API_KEY", None)
        env.pop("AGENTSCOPE_API_KEYS", None)
        env.update(extra_env or {})
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=SERVER_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                pytest.fail("server did not start")
            yield port
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


@pytest.fixture(scope="module")
def server():
    with _uvicorn() as port:
        yield port


def run_sdk_script(
    port, session_name, body, timeout=30, host="127.0.0.1", api_key=None
):
    prelude = (
        "from agentscope_trace.decorators import configure, get_global_client, trace\n"
        f"configure(host={host!r}, port={port}, session_name={session_name!r}, "
        f"api_key={api_key!r})\n"
    )
    env = {**os.environ}
    env.pop("AGENTSCOPE_API_KEY", None)
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return proc, time.monotonic() - started


def _api(port, path, api_key=None, body=None):
    """Call the server's REST API, with the API key when one is given."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    with urllib.request.urlopen(
        urllib.request.Request(
            f"http://127.0.0.1:{port}/api/{path}", data=data, headers=headers
        )
    ) as response:
        return json.load(response)


def session_ids_named(port, session_name, api_key=None):
    sessions = _api(port, "sessions?limit=100", api_key)["sessions"]
    return [s["session_id"] for s in sessions if s["name"] == session_name]


def stored_event_ids(port, session_name, api_key=None):
    match = session_ids_named(port, session_name, api_key)
    assert match, f"session {session_name!r} was not created"
    events = _api(port, f"sessions/{match[0]}/events?limit=1000", api_key)["events"]
    return {e["event_id"] for e in events}


def wait_for_event_count(port, session_name, expected, timeout=15.0, api_key=None):
    """The SDK may finish sending before the server has persisted everything
    (it ingests messages sequentially), so poll instead of reading once."""
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = len(stored_event_ids(port, session_name, api_key))
        if count >= expected:
            break
        time.sleep(0.2)
    return count


TRACE_30_CALLS = """
@trace(name="step")
def step(i):
    return i

for i in range(30):
    step(i)
"""


def test_script_without_stop_exits_and_delivers(server):
    session = f"e2e-no-stop-{uuid.uuid4().hex[:8]}"
    proc, elapsed = run_sdk_script(
        server, session, TRACE_30_CALLS + "import time; time.sleep(0.5)\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 15
    # 30 traced calls -> 30 stored events (start and end merged per call).
    assert wait_for_event_count(server, session, 30) == 30


def test_script_with_immediate_stop_delivers(server):
    session = f"e2e-stop-{uuid.uuid4().hex[:8]}"
    proc, elapsed = run_sdk_script(
        server, session, TRACE_30_CALLS + "get_global_client().stop(timeout=5)\n"
    )
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 15
    assert wait_for_event_count(server, session, 30) == 30


def test_short_script_without_stop_or_sleep_exits_fast_and_delivers(server):
    """The script ends right after its last call: no sleep, no stop().

    CPython shuts down the default executor before atexit hooks run, so the
    session POST and the name lookup for "localhost" must not depend on it.
    """
    session = f"e2e-short-{uuid.uuid4().hex[:8]}"
    proc, elapsed = run_sdk_script(server, session, TRACE_30_CALLS, host="localhost")
    assert proc.returncode == 0, proc.stderr
    assert elapsed < 3, f"exit took {elapsed:.1f}s"
    assert wait_for_event_count(server, session, 30) == 30
