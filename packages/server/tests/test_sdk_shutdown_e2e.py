"""End-to-end SDK shutdown against a real uvicorn server (#294).

Runs the SDK in separate interpreters, so the test observes exactly what a
user's script does: whether it exits and what reaches the database.
"""

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


@pytest.fixture(scope="module")
def server():
    port = _free_port()
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{tmp}/e2e.db"}
        env.pop("AGENTSCOPE_API_KEY", None)
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


def run_sdk_script(port, session_name, body, timeout=30):
    prelude = (
        "from agentscope.decorators import configure, get_global_client, trace\n"
        f"configure(host='127.0.0.1', port={port}, session_name={session_name!r})\n"
    )
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, "-c", prelude + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc, time.monotonic() - started


def stored_event_ids(port, session_name):
    sessions = json.load(
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions?limit=100")
    )["sessions"]
    match = [s for s in sessions if s["name"] == session_name]
    assert match, f"session {session_name!r} was not created"
    url = (
        f"http://127.0.0.1:{port}/api/sessions/"
        f"{match[0]['session_id']}/events?limit=1000"
    )
    return {e["event_id"] for e in json.load(urllib.request.urlopen(url))["events"]}


def wait_for_event_count(port, session_name, expected, timeout=15.0):
    """The SDK may finish sending before the server has persisted everything
    (it ingests messages sequentially), so poll instead of reading once."""
    deadline = time.monotonic() + timeout
    count = 0
    while time.monotonic() < deadline:
        count = len(stored_event_ids(port, session_name))
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
