# Performance

This page records measured performance against the targets in [`PRD.md`](PRD.md), explains how to reproduce the numbers, and lists what has not been measured.

> **Environment for every number below:** Apple M4 (10 cores), macOS 27.0.1, Python 3.11.16, one `uvicorn` worker, SQLite (WAL) on the local SSD, SDK and server from the same commit (`main` after #296, #287, #285 and #324, plus this change), measured 2026-11-20. The machine was otherwise lightly loaded (load average about 2). Shared CI runners are typically several times slower. Treat these numbers as indicative for this machine, not as guarantees.
>
> **Reading the tables:** each benchmark was repeated. Cells show the **median across runs**, with the **min–max range across runs** in brackets. "Worst max" is the single slowest sample seen in any run.

## Summary against PRD targets

| PRD target | Source | Measured | Status |
|---|---|---|---|
| `emit()` returns in < 1 ms and never blocks the agent | §9, `client.py` docstring | p99 **2.7 µs** with the server down, **2.8 µs** in a back-to-back burst, **20 µs** when paced at 500 ev/s. Single calls occasionally take longer: the worst of 225,000 timed calls was **5.0 ms** (server down) | ✅ at p99. Not every call is under 1 ms |
| Events visible in the UI within 100 ms | §6 | Median latency **≤ 3.6 ms** at 100–500 ev/s in every run. In the recorded runs, 3 s bursts had p95 ≤ 10.5 ms up to 500 ev/s, and 15 s bursts p95 ≤ 7 ms at 100 and 400 ev/s, except one 250 ev/s round that stalled (p95 285 ms, max 399 ms); 500 ev/s built a backlog (p95 117–659 ms). An independent rerun on the same machine saw stalls of 0.1–0.4 s at every rate from 250 to 500 ev/s (e.g. one 3 s round at 500 ev/s with p95 405 ms, one 15 s round at 400 ev/s with p95 81 ms) | ⚠️ Typical latency yes, up to ~400 ev/s. Occasional stalls of a few hundred ms push the tail above 100 ms |
| < 1 s latency under normal load | §9 | Every event arrived within 1 s at ≤ 500 ev/s in every run (worst **0.79 s**, 15 s at 500 ev/s). At 600 ev/s, 15 s bursts reach p99 **2.2 s**. Even 3 s bursts reach about 1 s at 750 ev/s (slowest event 0.98–1.12 s) and 2.3–2.5 s at 1,000 ev/s | ✅ up to 400 ev/s (worst 0.4 s). ⚠️ at 500 ev/s (worst 0.8 s). ❌ sustained ≥ 600 ev/s |
| No data loss on network hiccups | §6 | 300 of 300 events sent during a ~2.3 s outage were delivered in 5 of 5 runs. Beyond the buffer, the oldest events are dropped by design. Delivery completes **1.5 s** (1.4–1.6) after the restarted server is healthy | ✅ within buffer capacity (5,000 events by default) |
| < 5 min from clone to first event | §9 | Cold package caches: **20.5 s** (20.0–21.9) backend only, **34.8 s** (33.7–35.5) including the dashboard `npm ci` and build. Warm caches: 14.0 s and 23.3 s | ✅ for the steps measured. Opening the dashboard in a browser was not timed |

The SQLite server's throughput is roughly **500 ev/s** with one worker on this machine: 500 ev/s held for 15 s already built a backlog. Bursts above the throughput are queued, not lost (every event was stored at every rate), and latency grows with the length of the burst.

## SDK overhead (`benchmarks/bench_emit.py`)

Time spent on the caller's thread, in microseconds. 5 runs of each scenario.

| Scenario (µs) | n per run | p50 | p95 | p99 | Worst max | Stored | Dropped |
|---|---|---|---|---|---|---|---|
| `emit()`, server down (buffer full, evicting) | 20,000 | 1.58 (1.42–1.71) | 2.21 (1.62–3.08) | 2.67 (1.88–3.75) | 5,044 | n/a | n/a |
| `emit()`, server up, paced at 500 ev/s | 5,000 | 4.71 (4.33–4.83) | 18.92 (17.75–19.04) | 20.42 (20.29–20.92) | 218 | 5,000 | **0** |
| `emit()`, server up, back-to-back burst | 20,000 | 1.58 (1.42–1.58) | 2.21 (1.83–2.21) | 2.79 (1.96–3.17) | 475 | 5,101–5,151 | **14,849–14,899** |
| plain function call | 5,000 | 0.08 (0.08–0.17) | 0.12 (0.12–0.17) | 0.17 (0.12–0.21) | 7 | n/a | n/a |
| `@trace`-decorated call (server down) | 5,000 | 9.00 (8.21–10.67) | 13.25 (9.29–16.75) | 16.12 (10.42–22.08) | 484 | n/a | n/a |

- `emit()` only enqueues. Networking happens on a background thread.
- **The burst row is the overflow path, not the normal case.** 20,000 back-to-back emits take a few milliseconds, far faster than the sender can deliver, so the 5,000-event buffer fills and the oldest events are evicted. About 74% of the burst was dropped (the ~100 kept beyond 5,000 were already in flight). Use the **paced** row for normal operation: every event was stored.
- Paced emits are slower than back-to-back ones (p95 ≈ 19 µs vs 2 µs). The likely causes are cold CPU caches after each sleep and the cost of waking the idle sender thread, which an emit in a tight loop rarely pays. This was not profiled further. It is still about 50× under the 1 ms budget.
- `@trace` costs about 9 µs per call because it builds start/end payloads and timestamps.
- The worst single calls (up to 5 ms, server down) are rare outliers, most likely thread scheduling or garbage collection on the caller's thread. They are outside p99 in every run.

## End-to-end latency (`benchmarks/bench_e2e_latency.py`)

SDK `emit()` → WebSocket → server persists to SQLite → broadcast to a dashboard-style `/ws?client_type=ui` subscriber. Emitter and subscriber share one process and one monotonic clock. This measures the time until the dashboard's WebSocket receives the event, not until the browser paints it.

### 3-second bursts, 5 rounds (each round on a fresh server and database)

| Rate (ev/s) | Sent per run | Broadcast | Stored | p50 ms | p95 ms | p99 ms | Worst max ms |
|---|---|---|---|---|---|---|---|
| 10 | 30 | 30 | 30 | 8.1 (5.6–8.6) | 9.8 (9.0–10.4) | 10.4 (9.8–10.6) | 11 |
| 100 | 300 | 300 | 300 | 3.5 (3.5–3.5) | 4.2 (4.1–4.6) | 5.1 (4.5–6.7) | 10 |
| 250 | 750 | 750 | 750 | 2.4 (2.3–2.4) | 2.7 (2.6–2.7) | 5.9 (3.5–8.2) | 15 |
| 400 | 1,200 | 1,200 | 1,200 | 1.9 (1.9–1.9) | 2.6 (2.5–8.5) | 14.9 (7.7–15.8) | 20 |
| 500 | 1,500 | 1,500 | 1,500 | 1.9 (1.9–2.0) | 5.2 (2.7–6.4) | 12.7 (4.6–24.1) | 25 |
| 600 | 1,800 | 1,800 | 1,800 | 51 (37–85) | 150 (94–207) | 154 (97–249) | 257 |
| 750 | 2,250 | 2,250 | 2,250 | 568 (464–621) | 997 (935–1,074) | 1,057 (973–1,112) | 1,122 |
| 1,000 | 3,000 | 3,000 | 3,000 | 1,135 (1,112–1,222) | 2,222 (2,153–2,360) | 2,322 (2,245–2,464) | 2,489 |

### 15-second bursts, 3 rounds

A 3 s burst can hide a slow backlog, so the rates near the knee were repeated with 15 s bursts.

| Rate (ev/s) | Sent per run | Stored | p50 ms | p95 ms | p99 ms | Worst max ms |
|---|---|---|---|---|---|---|
| 100 | 1,500 | 1,500 | 3.5 (3.5–3.5) | 4.1 (4.1–6.7) | 5.0 (4.9–79.9) | 103 |
| 250 | 3,750 | 3,750 | 2.4 (2.4–2.4) | 2.9 (2.6–284.9) | 6.0 (2.8–376.6) | 399 |
| 400 | 6,000 | 6,000 | 2.0 (2.0–2.1) | 2.7 (2.6–7.0) | 4.2 (3.0–17.4) | 48 |
| 500 | 7,500 | 7,500 | 2.7 (2.5–2.8) | 329 (117–659) | 664 (150–784) | 794 |
| 600 | 9,000 | 9,000 | 622 (593–719) | 2,016 (1,911–2,187) | 2,204 (2,102–2,388) | 2,448 |

What the data supports:

- **Every event was delivered and stored at every rate.** Above the server's throughput, events queue rather than drop.
- **Throughput is about 500 ev/s** with one worker on SQLite. Each event is persisted in its own transaction before it is broadcast. At 500 ev/s, 3 s bursts keep up, but 15 s bursts built a backlog in all three rounds. 15 s bursts at 600 ev/s ended about 2.2 s behind, which implies a drain rate of about 520 ev/s. Batched persistence on the server would be the main lever for higher sustained rates.
- **Stalls happen well below that.** In the recorded runs, one 15 s round at 250 ev/s had a stall of about 0.4 s, and one at 100 ev/s had a single 103 ms event. An independent rerun saw 0.1–0.4 s stalls at 250, 400 and 500 ev/s too, so treat them as a recurring tail effect at these rates, not a one-off. The cause (SQLite WAL checkpoint, garbage collection, or OS scheduling) was not investigated. Single runs therefore say little about the tail: an earlier single run at 500 ev/s reported a p95 of 1.5 s on the pre-#296 SDK, which these runs did not reproduce.
- At 10 ev/s the median (8 ms) is higher than at 100 ev/s (3.5 ms). The machine idles between events at low rates, and waking it probably costs a few milliseconds. This was not investigated.

## Outage and recovery (`benchmarks/bench_resilience.py`)

The server is stopped mid-session while the SDK keeps emitting for about 1 s, then restarted on the same port and database. 5 runs per scenario.

| Scenario | Buffer | Sent during outage | Delivered after restart | Kept event ids | Outage s | Server start s | Recovery s |
|---|---|---|---|---|---|---|---|
| A: outage within buffer | 5,000 | 300 | 300 (all runs) | 0–299 | 2.28 (2.18–2.36) | 0.56 (0.55–0.67) | 1.48 (1.39–1.56) |
| B: outage overflows buffer | 500 | 2,000 | 501 (all runs) | 0, 1500–1999 | 2.32 (2.25–2.50) | 0.56 (0.55–0.66) | 1.87 (1.71–1.89) |

- **Outage** runs from stopping the server until the restarted one answers `/health`. **Server start** is the uvicorn start-up part of that. **Recovery** starts only once the server is healthy and ends when every expected event is stored, so it measures the SDK alone.
- Recovery is mostly the wait for the SDK's next reconnect attempt. Retries back off at 1 s, 2 s, 4 s and so on, up to 30 s, counted from the first failure. After this ~2.3 s outage the next attempt was due about 1.5 s after the server came back. **Longer outages recover more slowly** (up to 30 s after the server returns). Only ~2.3 s outages were measured.
- The SDK buffers up to `max_queue_size` events (default **5,000**, configurable on `AgentScopeClient`). When the buffer is full, the **oldest** buffered events are dropped so `emit()` never blocks.
- In scenario B, event 0 also survived. The sender had already taken it off the buffer when the first send failed, kept it aside, and delivered it first after reconnecting. The rest are exactly the newest 500.

## Time to value (`scripts/ttv_check.sh`)

Fresh clone of the repository into a temporary directory, a fresh virtualenv, and the README manual-setup steps, ending when the first event is stored (checked through the REST API). 3 runs per column.

- **Cold** (`--cold`): the pip cache is disabled and npm gets an empty cache, so every package is downloaded. DNS/TLS caches were not cleared, and network bandwidth was not measured.
- **Warm** (default): pip and npm reuse the machine's caches, which already held these packages.

| Step (s) | Cold, backend only | Cold, with dashboard | Warm, backend only | Warm, with dashboard |
|---|---|---|---|---|
| git clone | 0.1 (0.1–0.2) | 0.1 | 0.1 | 0.1 |
| create virtualenv | 1.5 (1.5–1.7) | 1.5 | 1.6 (1.5–1.6) | 1.6 |
| pip install server | 14.5 (13.8–15.7) | 13.3 (13.1–15.4) | 8.8 (8.4–9.4) | 9.2 (9.0–9.7) |
| pip install SDK | 2.4 (2.3–2.7) | 2.5 (2.4–2.8) | 1.6 | 1.6 (1.6–1.8) |
| start server | 1.8 (1.7–1.9) | 2.4 (2.0–2.8) | 1.8 (1.7–3.8) | 1.8 (1.7–2.6) |
| first event stored | 0.2 (0.1–0.2) | 0.1 (0.1–0.2) | 0.2 (0.1–0.2) | 0.2 (0.1–0.2) |
| npm ci (dashboard) | n/a | 9.6 (9.3–10.1) | n/a | 4.4 (3.8–4.4) |
| npm run build (dashboard) | n/a | 4.1 (4.0–4.6) | n/a | 4.2 (4.0–4.7) |
| **Total** | **20.5 (20.0–21.9)** | **34.8 (33.7–35.5)** | **14.0 (13.7–16.7)** | **23.3 (22.9–24.1)** |

Downloads dominate a cold run, so a slower connection changes the totals most. The dashboard columns were measured just before [#320](https://github.com/PxA-Labs/AgentsScope/pull/320) bumped React; they were not re-run after it. Not timed: starting the dashboard (`npm start`) and seeing the event in a browser, the Docker Compose path, and a machine without Python 3.11 or Node already installed.

## CI regression gate (`packages/sdk/tests/test_performance.py`)

Every PR runs a lightweight gate with deliberately generous budgets:

| Check | Budget | Local value (median of 10 runs, min–max) | Headroom |
|---|---|---|---|
| `emit()` p99, server unreachable, 5,000 calls | 1,000 µs | 2.4 µs (1.3–4.0) | ~400× |
| `@trace` p50 with a no-op client, 2,000 calls | 500 µs | 9.2 µs (5.3–9.7) | ~55× |

The gate passed **10 of 10** runs with the CPU 2× oversubscribed (20 busy processes on 10 cores, re-checked after merging #296). Under that load the measured values stayed at emit p99 ≤ 2.6 µs and `@trace` p50 ≤ 9.6 µs (10 runs each), so neither budget was close.

## Findings while benchmarking

- **`AgentScopeClient.stop()` could hang forever** once the buffer was full (server down for more than 5,000 events). Reported as [#289](https://github.com/PxA-Labs/AgentsScope/issues/289) and fixed in [#290](https://github.com/PxA-Labs/AgentsScope/pull/290). The benchmarks no longer work around it: they call `stop()` (with `timeout=0` when the server is down and nothing can be delivered).
- `stop()` returns once buffered events are written to the socket, not when the server has committed them. The benchmarks therefore count stored events only after the server's count stops changing.
- `flush_interval_seconds` is now the sender's safety-net wake-up period ([#296](https://github.com/PxA-Labs/AgentsScope/pull/296)). New events wake the sender immediately, so it adds no latency, and these benchmarks use the default.

## Not measured

- **PostgreSQL.** The harness starts SQLite only. Running `make bench` against a Postgres `DATABASE_URL` is a follow-up.
- **More than one uvicorn worker or more than one SDK client** sending at the same time.
- **Linux or CI-runner numbers.** The weekly workflow produces them, but none are recorded here.
- **Browser rendering.** End-to-end latency stops at the dashboard's WebSocket, not at paint.
- **Bursts longer than 15 s, and outages longer than ~2.5 s.**
- **The cause of the occasional stalls** described above.

## Reproducing

```bash
pip install -r packages/server/requirements.txt -e packages/sdk
make bench            # emit overhead, end-to-end latency, resilience (5 runs each)
make ttv              # time to value with the machine's caches
scripts/ttv_check.sh --cold --with-ui   # cold caches, including the dashboard build
python benchmarks/bench_e2e_latency.py --rates 250 400 500 600 --duration 15 --repeat 3
```

- Every benchmark takes `--repeat` (default 5) and prints each run as well as the median (min–max) summary.
- The `Benchmarks` GitHub Actions workflow runs `make bench` weekly and on demand, fails if any benchmark fails, and attaches the results.
