"""End-to-end latency: SDK emit() -> server persist -> UI WebSocket broadcast.

A UI-style WebSocket subscriber (the same /ws?client_type=ui endpoint the
dashboard uses) timestamps each broadcast. Emitter and subscriber share one
process and one monotonic clock, so latencies are directly comparable.

Run: python benchmarks/bench_e2e_latency.py [--rates 10 100 1000] [--duration 3]
"""

import argparse
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import websockets
from _harness import count_events, make_event, percentiles, print_table, running_server
from agentscope.client import AgentScopeClient


class Subscriber:
    def __init__(self, port: int, session_id: str):
        self.url = f"ws://127.0.0.1:{port}/ws?client_type=ui&session_id={session_id}"
        self.received = {}
        self.ready = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "Subscriber":
        self._thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("subscriber failed to connect")
        return self

    def _run(self) -> None:
        asyncio.run(self._listen())

    async def _listen(self) -> None:
        async with websockets.connect(self.url) as ws:
            self.ready.set()
            while not self._stop.is_set():
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                now = time.perf_counter()
                msg = json.loads(raw)
                if msg.get("type") == "event":
                    self.received.setdefault(msg["event"]["event_id"], now)

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(5)


def run_rate(port: int, rate: int, duration: float) -> dict:
    client = AgentScopeClient(host="127.0.0.1", port=port, session_name=f"lat-{rate}")
    client.emit(make_event(f"warmup-{rate}"))
    deadline = time.monotonic() + 10
    while client.session_id is None and time.monotonic() < deadline:
        time.sleep(0.01)
    session_id = client.session_id
    sub = Subscriber(port, session_id).start()
    time.sleep(0.3)

    n = int(rate * duration)
    interval = 1.0 / rate
    emitted = {}
    next_at = time.perf_counter()
    for i in range(n):
        event_id = f"r{rate}-{i}"
        emitted[event_id] = time.perf_counter()
        client.emit(make_event(event_id))
        next_at += interval
        delay = next_at - time.perf_counter()
        if delay > 0:
            time.sleep(delay)

    wait_until = time.monotonic() + 10
    while time.monotonic() < wait_until and not all(e in sub.received for e in emitted):
        time.sleep(0.05)
    sub.stop()
    client.stop()

    latencies = [
        (sub.received[e] - t) * 1000 for e, t in emitted.items() if e in sub.received
    ]
    stored = count_events(port, session_id) - 1  # minus warmup
    stats = percentiles(latencies)
    return {
        "rate (ev/s)": rate,
        "sent": n,
        "broadcast": len(latencies),
        "stored": stored,
        "p50 ms": stats.get("p50", float("nan")),
        "p95 ms": stats.get("p95", float("nan")),
        "p99 ms": stats.get("p99", float("nan")),
        "max ms": stats.get("max", float("nan")),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rates", type=int, nargs="+", default=[10, 100, 1000])
    parser.add_argument("--duration", type=float, default=3.0)
    args = parser.parse_args()

    rows = []
    with running_server() as server:
        for rate in args.rates:
            rows.append(run_rate(server.port, rate, args.duration))
    print_table(
        "End-to-end latency, emit() -> UI broadcast (SQLite)",
        rows,
        [
            "rate (ev/s)",
            "sent",
            "broadcast",
            "stored",
            "p50 ms",
            "p95 ms",
            "p99 ms",
            "max ms",
        ],
    )


if __name__ == "__main__":
    main()
