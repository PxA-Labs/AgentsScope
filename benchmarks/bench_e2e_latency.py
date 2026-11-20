"""End-to-end latency: SDK emit() -> server persist -> UI WebSocket broadcast.

A UI-style WebSocket subscriber (the same /ws?client_type=ui endpoint the
dashboard uses) timestamps each broadcast. Emitter and subscriber share one
process and one monotonic clock, so latencies are directly comparable.

Single runs are noisy (a GC pause or SQLite checkpoint can move p95 by an
order of magnitude), so the whole sweep is repeated --repeat times, each round
on a fresh server and database. The summary shows the median across rounds
with the min-max range in brackets; the per-round rows are printed too.

Run: python benchmarks/bench_e2e_latency.py [--rates 10 100 1000] [--duration 3]
     [--repeat 5]
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
from _harness import (
    int_range,
    machine_info,
    make_event,
    percentiles,
    print_table,
    running_server,
    settled_count,
    spread,
)
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
    stored = settled_count(port, session_id, n + 1) - 1  # minus warmup
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


COLUMNS = ["rate (ev/s)", "sent", "broadcast", "stored", "p50 ms", "p95 ms", "p99 ms"]


def summarize(rate: int, runs: list) -> dict:
    return {
        "rate (ev/s)": rate,
        "runs": len(runs),
        "sent/run": f"{runs[0]['sent']:,}",
        "broadcast": int_range([r["broadcast"] for r in runs]),
        "stored": int_range([r["stored"] for r in runs]),
        "p50 ms": spread([r["p50 ms"] for r in runs]),
        "p95 ms": spread([r["p95 ms"] for r in runs]),
        "p99 ms": spread([r["p99 ms"] for r in runs]),
        "worst max ms": f"{max(r['max ms'] for r in runs):,.0f}",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rates",
        type=int,
        nargs="+",
        default=[10, 100, 250, 400, 500, 600, 750, 1000],
    )
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    by_rate = {rate: [] for rate in args.rates}
    for round_no in range(1, args.repeat + 1):
        rows = []
        with running_server() as server:
            for rate in args.rates:
                row = run_rate(server.port, rate, args.duration)
                by_rate[rate].append(row)
                rows.append(row)
        print_table(f"Round {round_no}", rows, COLUMNS + ["max ms"])

    print(f"\nMachine: {machine_info()}")
    print_table(
        "End-to-end latency, emit() -> UI broadcast (SQLite), "
        f"median (min–max) over {args.repeat} rounds",
        [summarize(rate, runs) for rate, runs in by_rate.items()],
        [
            "rate (ev/s)",
            "runs",
            "sent/run",
            "broadcast",
            "stored",
            "p50 ms",
            "p95 ms",
            "p99 ms",
            "worst max ms",
        ],
    )


if __name__ == "__main__":
    main()
