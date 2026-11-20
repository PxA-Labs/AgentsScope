"""SDK overhead on the caller's thread.

Measures, in microseconds, the time AgentScopeClient.emit() and @trace take on
the calling thread, in four situations:

1. Server down: the buffer fills after max_queue_size events, so most calls
   take the evict-oldest path.
2. Server up, emits paced at a rate the server sustains: the normal case.
   Reports how many events were stored, which should be all of them.
3. Server up, back-to-back burst: emit() outruns the sender, the buffer
   overflows and the oldest events are dropped. Reports how many.
4. @trace on a trivial function, against an unreachable server.

Each scenario runs --repeat times; the tables show the median across runs,
with the min-max range in brackets.

Run: python benchmarks/bench_emit.py [--repeat 5] [--n 20000]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import (
    free_port,
    int_range,
    machine_info,
    make_event,
    percentiles,
    print_table,
    running_server,
    settled_count,
    spread,
)
from agentscope import decorators
from agentscope.client import AgentScopeClient


def time_emits(client: AgentScopeClient, n: int, rate: float = 0.0) -> list:
    """Time n emit() calls; with rate > 0, pace them at that many per second."""
    client.emit(make_event("warmup"))  # starts the background thread
    time.sleep(0.2)
    samples = []
    interval = 1.0 / rate if rate else 0.0
    next_at = time.perf_counter()
    for i in range(n):
        event = make_event(f"e{i}")
        t0 = time.perf_counter_ns()
        client.emit(event)
        samples.append((time.perf_counter_ns() - t0) / 1000)
        if interval:
            next_at += interval
            delay = next_at - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
    return samples


def emit_server_down(n: int) -> dict:
    client = AgentScopeClient(host="127.0.0.1", port=free_port(), session_name="down")
    try:
        samples = time_emits(client, n)
    finally:
        # Nothing can be delivered; do not wait for it.
        client.stop(timeout=0)
    return {**percentiles(samples), "sent": n, "stored": 0}


def emit_server_up(n: int, rate: float) -> dict:
    with running_server() as server:
        client = AgentScopeClient(
            host="127.0.0.1", port=server.port, session_name="emit-bench"
        )
        samples = time_emits(client, n, rate)
        # stop() delivers whatever is still buffered (#296).
        client.stop(timeout=30)
        # minus the warmup event
        stored = settled_count(server.port, client.session_id, n + 1) - 1
    return {**percentiles(samples), "sent": n, "stored": stored}


def trace_overhead(n: int) -> list:
    decorators.configure(host="127.0.0.1", port=free_port(), session_name="trace")

    def plain(x):
        return x + 1

    traced = decorators.trace(name="traced")(plain)
    traced(0)  # warm up client thread

    def measure(fn):
        out = []
        for i in range(n):
            t0 = time.perf_counter_ns()
            fn(i)
            out.append((time.perf_counter_ns() - t0) / 1000)
        return out

    base = percentiles(measure(plain))
    with_trace = percentiles(measure(traced))
    decorators.get_global_client().stop(timeout=0)
    return [base, with_trace]


def summarize(name: str, runs: list, delivery: bool) -> dict:
    row = {"scenario": name, "runs": len(runs), "n/run": f"{runs[0]['n']:,}"}
    for key in ("p50", "p95", "p99"):
        row[key] = spread([r[key] for r in runs], 2)
    row["worst max"] = f"{max(r['max'] for r in runs):,.0f}"
    if delivery:
        row["stored"] = int_range([r["stored"] for r in runs])
        row["dropped"] = int_range([r["sent"] - r["stored"] for r in runs])
    else:
        row["stored"] = row["dropped"] = "n/a"
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--n", type=int, default=20000, help="burst/down emits")
    parser.add_argument("--paced-n", type=int, default=5000)
    parser.add_argument("--paced-rate", type=float, default=500.0)
    args = parser.parse_args()

    down, paced, burst, plain, traced = [], [], [], [], []
    for _ in range(args.repeat):
        down.append(emit_server_down(args.n))
        paced.append(emit_server_up(args.paced_n, args.paced_rate))
        burst.append(emit_server_up(args.n, 0.0))
        base, with_trace = trace_overhead(args.n // 4)
        plain.append(base)
        traced.append(with_trace)

    print(f"\nMachine: {machine_info()}")
    print_table(
        f"SDK emit() and @trace time on the caller thread (µs), {args.repeat} runs",
        [
            summarize("emit(), server down (buffer full, evicting)", down, False),
            summarize(
                f"emit(), server up, paced {args.paced_rate:,.0f} ev/s", paced, True
            ),
            summarize("emit(), server up, back-to-back burst", burst, True),
            summarize("plain function call", plain, False),
            summarize("@trace function call (server down)", traced, False),
        ],
        [
            "scenario",
            "runs",
            "n/run",
            "p50",
            "p95",
            "p99",
            "worst max",
            "stored",
            "dropped",
        ],
    )


if __name__ == "__main__":
    main()
