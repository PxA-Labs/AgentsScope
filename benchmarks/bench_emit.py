"""SDK overhead on the caller's thread.

Measures, in microseconds:
1. AgentScopeClient.emit() with the server down (worst case: the buffer fills
   and starts evicting) and with a live server draining the queue.
2. The wall-clock overhead @trace adds to a trivial function.

Run: python benchmarks/bench_emit.py [--n 20000]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import free_port, make_event, percentiles, print_table, running_server
from agentscope import decorators
from agentscope.client import AgentScopeClient


def time_emits(client: AgentScopeClient, n: int) -> list:
    client.emit(make_event("warmup"))  # starts the background thread
    time.sleep(0.2)
    samples = []
    for i in range(n):
        event = make_event(f"e{i}")
        t0 = time.perf_counter_ns()
        client.emit(event)
        samples.append((time.perf_counter_ns() - t0) / 1000)
    return samples


def _drain(client: AgentScopeClient) -> None:
    # Until #289 is fixed, stop() blocks forever on a full buffer, which the
    # server-down scenario deliberately produces. Empty it first.
    while True:
        try:
            client.queue.get_nowait()
        except Exception:
            return


def bench_emit_server_down(n: int) -> dict:
    client = AgentScopeClient(host="127.0.0.1", port=free_port(), session_name="down")
    try:
        return {"scenario": "emit(), server down", **percentiles(time_emits(client, n))}
    finally:
        _drain(client)
        client.stop()


def bench_emit_server_up(n: int) -> dict:
    with running_server() as server:
        client = AgentScopeClient(
            host="127.0.0.1", port=server.port, session_name="emit-bench"
        )
        try:
            samples = time_emits(client, n)
        finally:
            client.stop()
    return {"scenario": "emit(), server up", **percentiles(samples)}


def bench_trace_overhead(n: int) -> list:
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
    _drain(decorators.get_global_client())
    decorators.get_global_client().stop()
    return [
        {"scenario": "plain function", **base},
        {"scenario": "@trace function", **with_trace},
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20000)
    args = parser.parse_args()

    cols = ["scenario", "n", "p50", "p95", "p99", "max", "mean"]
    print_table(
        "SDK emit() latency on the caller thread (µs)",
        [bench_emit_server_down(args.n), bench_emit_server_up(args.n)],
        cols,
    )
    print_table(
        "@trace overhead per call (µs)", bench_trace_overhead(args.n // 4), cols
    )


if __name__ == "__main__":
    main()
