"""Regression gate for SDK overhead on the caller's thread.

Thresholds are deliberately generous (about 400x the locally measured p99 of
roughly 2.5 µs, see docs/PERFORMANCE.md) so that slow, shared CI runners do not
flake, while still catching a regression such as emit() starting to block on
I/O or locks. The PRD target is "emit() returns in < 1 ms".
"""

import socket
import time

from agentscope.client import AgentScopeClient
from agentscope.decorators import trace

EMIT_P99_BUDGET_US = 1000.0
TRACE_P50_BUDGET_US = 500.0


def _unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _p(samples, pct):
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(pct / 100 * len(ordered)))]


def _drain(client):
    while not client.queue.empty():
        client.queue.get_nowait()


def test_emit_p99_under_budget_with_server_unreachable():
    client = AgentScopeClient(
        host="127.0.0.1", port=_unused_port(), max_queue_size=20000
    )
    client.emit({"event_id": "warmup"})  # starts the background thread
    time.sleep(0.1)
    samples = []
    for i in range(5000):
        event = {"event_id": str(i), "event_type": "tool_end", "payload": {}}
        t0 = time.perf_counter_ns()
        client.emit(event)
        samples.append((time.perf_counter_ns() - t0) / 1000)
    _drain(client)
    client.stop()
    assert _p(samples, 99) < EMIT_P99_BUDGET_US, f"p99={_p(samples, 99):.1f}µs"


def test_trace_decorator_overhead_under_budget(monkeypatch):
    class NullClient:
        def emit(self, event):
            pass

    monkeypatch.setattr("agentscope.decorators.get_global_client", NullClient)

    @trace(name="hot_path")
    def work(x):
        return x + 1

    samples = []
    for i in range(2000):
        t0 = time.perf_counter_ns()
        work(i)
        samples.append((time.perf_counter_ns() - t0) / 1000)
    assert _p(samples, 50) < TRACE_P50_BUDGET_US, f"p50={_p(samples, 50):.1f}µs"
