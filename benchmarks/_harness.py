"""Shared helpers for AgentScope benchmarks (not imported by the packages)."""

import contextlib
import json
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = REPO_ROOT / "packages" / "server"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_health(port: int, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=1
            ) as res:
                if res.status == 200:
                    return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"server on port {port} did not become healthy")


class ServerProcess:
    """A real uvicorn server on a throwaway SQLite database."""

    def __init__(self, port: Optional[int] = None, db_path: Optional[Path] = None):
        self.port = port or free_port()
        self._tmp = None
        if db_path is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="agentscope-bench-")
            db_path = Path(self._tmp.name) / "bench.db"
        self.db_path = db_path
        self.proc: Optional[subprocess.Popen] = None

    def start(self) -> "ServerProcess":
        env = {
            **os.environ,
            "DATABASE_URL": f"sqlite+aiosqlite:///{self.db_path}",
        }
        env.pop("AGENTSCOPE_API_KEY", None)
        env.pop("AGENTSCOPE_API_KEYS", None)
        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            cwd=SERVER_DIR,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_for_health(self.port)
        return self

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def cleanup(self) -> None:
        self.stop()
        if self._tmp is not None:
            self._tmp.cleanup()


@contextlib.contextmanager
def running_server() -> Iterator[ServerProcess]:
    server = ServerProcess().start()
    try:
        yield server
    finally:
        server.cleanup()


def get_json(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.loads(r.read())


def count_events(port: int, session_id: str) -> int:
    """Count stored events for a session by walking the paginated API."""
    total, page = 0, 1
    while True:
        data = get_json(
            port, f"/api/sessions/{session_id}/events?page={page}&limit=500"
        )
        events = data.get("events", [])
        total += len(events)
        if len(events) < 500:
            return total
        page += 1


def make_event(event_id: str) -> Dict:
    from datetime import datetime, timezone

    return {
        "event_id": event_id,
        "session_id": "",
        "parent_event_id": None,
        "event_type": "tool_end",
        "agent_name": "bench",
        "agent_type": "tool",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "latency_ms": 1,
        "status": "completed",
        "payload": {"tool_name": "bench", "input": "x", "output": "y"},
    }


def percentiles(samples: Sequence[float]) -> Dict[str, float]:
    if not samples:
        return {"n": 0}
    ordered = sorted(samples)

    def pct(p: float) -> float:
        k = min(len(ordered) - 1, max(0, round(p / 100 * (len(ordered) - 1))))
        return ordered[k]

    return {
        "n": len(ordered),
        "p50": pct(50),
        "p95": pct(95),
        "p99": pct(99),
        "max": ordered[-1],
        "mean": statistics.fmean(ordered),
    }


def print_table(title: str, rows: List[Dict], columns: List[str]) -> None:
    print(f"\n## {title}\n")
    print("| " + " | ".join(columns) + " |")
    print("|" + "|".join("---" for _ in columns) + "|")
    for row in rows:
        cells = []
        for col in columns:
            value = row.get(col, "")
            cells.append(f"{value:.3f}" if isinstance(value, float) else str(value))
        print("| " + " | ".join(cells) + " |")
