# Performance

This page records measured performance against the targets in [`PRD.md`](PRD.md) and explains how to reproduce the numbers.

> **Environment for the numbers below:** Apple M4 (10 cores), macOS, Python 3.11, single `uvicorn` worker, SQLite (WAL) on local SSD, measured 2026-11-15. Shared CI runners are typically several times slower. Treat these as indicative, not guarantees.

## Summary against PRD targets

| PRD target | Source | Measured | Status |
|---|---|---|---|
| `emit()` returns in < 1 ms, no blocking of the agent | §9, `client.py` docstring | p99 **2.5 µs**, p50 1.6 µs (server up or down). Rare outliers up to 13 ms with the server up (thread/GC scheduling) | ✅ at p99 |
| Events visible in the UI within 100 ms | §6 | p95 **5 ms** at 100 ev/s, 29 ms at 500 ev/s. Breaks down above ~600 ev/s | ✅ up to ~500 ev/s |
| < 1 s latency under normal load | §9 | ✅ up to ~500 ev/s. ❌ at ≥ 750 ev/s (backlog grows; see below) | ✅ normal load |
| No data loss on network hiccups | §6 | 100% delivered across a server restart within buffer capacity; recovery **≈ 2.5 s** after restart | ✅ |
| < 5 min from clone to first event | §9 | **32 s** backend only, **21 s** including dashboard `npm ci` + build (warm pip/npm caches) | ✅ |

## SDK overhead (`benchmarks/bench_emit.py`)

| Scenario (µs) | n | p50 | p95 | p99 | max |
|---|---|---|---|---|---|
| `emit()`, server down | 20,000 | 1.67 | 2.33 | 2.71 | 434 |
| `emit()`, server up | 20,000 | 1.58 | 2.13 | 2.50 | 13,302 |
| plain function call | 5,000 | 0.04 | 0.08 | 0.08 | 0.3 |
| `@trace`-decorated call | 5,000 | 8.6 | 10.0 | 14.7 | 237 |

`emit()` only enqueues. Networking happens on a background thread. `@trace` costs about 9 µs per call because it builds start/end payloads and timestamps.

## End-to-end latency (`benchmarks/bench_e2e_latency.py`)

SDK `emit()` → WebSocket → server persists to SQLite → broadcast to a dashboard-style `/ws?client_type=ui` subscriber.

| Rate (ev/s) | Sent | Broadcast | Stored | p50 ms | p95 ms | p99 ms | max ms |
|---|---|---|---|---|---|---|---|
| 10 | 30 | 30 | 30 | 7.8 | 11.2 | 12.3 | 12.3 |
| 100 | 300 | 300 | 300 | 3.1 | 5.1 | 18.9 | 31.5 |
| 250 | 750 | 750 | 750 | 2.1 | 21.8 | 60.8 | 70.5 |
| 500 | 1,500 | 1,500 | 1,500 | 1.9 | 28.7 | 36.6 | 39.2 |
| 750 | 2,250 | 2,250 | 2,250 | 482 | 950 | 991 | 1,002 |
| 1,000 | 3,000 | 3,000 | 3,000 | 1,312 | 2,475 | 2,581 | 2,607 |

Every event was delivered and stored at every rate. Above roughly 600 ev/s, a single server worker on SQLite can't keep up: each event is persisted in its own transaction before being broadcast. The queue builds up, so latency grows with the length of the burst rather than events being lost. Typical agent pipelines emit far fewer than 100 ev/s. Batched persistence on the server would be the main lever if higher sustained rates are needed.

## Outage and recovery (`benchmarks/bench_resilience.py`)

The server is stopped mid-session while the SDK keeps emitting, then restarted on the same port and database.

| Scenario | Buffer | Sent during outage | Delivered after restart | Kept event ids | Recovery |
|---|---|---|---|---|---|
| A: outage within buffer | 5,000 | 300 | 300 | 0–299 | 2.5 s |
| B: outage overflows buffer | 500 | 2,000 | 501 | 0, 1500–1999 | 2.7 s |

- The SDK buffers up to `max_queue_size` events (default **5,000**, configurable on `AgentScopeClient`). When the buffer is full, the **oldest** buffered events are dropped so `emit()` never blocks.
- In scenario B, event 0 also survived. It had already been taken off the queue by the sender when the outage began, and it's retried after reconnecting.
- Recovery time is dominated by the SDK's reconnect backoff (1 s, doubling, capped at 30 s), so longer outages recover more slowly.

## Time to value (`scripts/ttv_check.sh`)

Fresh clone of the repository into a temporary directory, a fresh virtualenv, and the README manual-setup steps:

| Step | Backend only | With dashboard |
|---|---|---|
| git clone | 0.1 s | 0.1 s |
| create virtualenv | 1.3 s | 1.3 s |
| pip install server | 27.4 s | 7.0 s |
| pip install SDK | 1.2 s | 1.1 s |
| start server | 2.0 s | 1.8 s |
| first event stored | 0.2 s | 0.2 s |
| npm ci (dashboard) | n/a | 5.5 s |
| npm run build (dashboard) | n/a | 4.5 s |
| **Total** | **32.3 s** | **21.4 s** |

Package caches were warm (the second run reused the pip cache from the first). On a cold machine, downloads dominate and depend on bandwidth.

## Findings while benchmarking

- **`AgentScopeClient.stop()` could hang forever** once the buffer was full (server down for more than 5,000 events). Reported as [#289](https://github.com/PxA-Labs/AgentsScope/issues/289) and fixed in [#290](https://github.com/PxA-Labs/AgentsScope/pull/290). Until that's merged, the benchmarks drain the buffer before stopping the client.
- `AgentScopeClient(flush_interval_seconds=...)` is accepted and stored but never used: batches are sent as soon as events are available (up to `batch_size`). Either wire it up or remove it.

## Reproducing

```bash
pip install -r packages/server/requirements.txt -e packages/sdk
make bench            # emit overhead, end-to-end latency, resilience
make ttv              # time to value (add --with-ui via scripts/ttv_check.sh)
python benchmarks/bench_e2e_latency.py --rates 250 500 750 --duration 3
```

- The `Benchmarks` GitHub Actions workflow runs `make bench` weekly and on demand, and attaches the results.
- Every PR runs a lightweight regression gate (`packages/sdk/tests/test_performance.py`): `emit()` p99 < 1 ms and `@trace` p50 < 0.5 ms.
