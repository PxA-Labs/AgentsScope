"""SDK behaviour across a server outage.

Scenario A: the server is stopped mid-session while the SDK keeps emitting,
then restarted on the same port and database. Counts how many events arrive
and how long the SDK takes to deliver them once the server is back.

Scenario B: same, but the outage produces more events than the SDK buffer
holds (max_queue_size), showing the drop-oldest policy.

Timing: "server start" is how long the restarted uvicorn takes to answer
/health. "Recovery" starts only after that, so it measures the SDK alone:
the wait for its next reconnect attempt (exponential backoff 1 s, 2 s, 4 s...
counted from the outage) plus delivering the buffer. Each scenario runs
--repeat times; the summary shows the median with the min-max range.

Run: python benchmarks/bench_resilience.py [--repeat 5]
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import (
    ServerProcess,
    count_events,
    get_json,
    int_range,
    machine_info,
    make_event,
    print_table,
    spread,
)
from agentscope.client import AgentScopeClient


def wait_for_count(port: int, session_id: str, expected: int, timeout: float) -> tuple:
    start = time.monotonic()
    count = 0
    while time.monotonic() - start < timeout:
        try:
            count = count_events(port, session_id)
        except OSError:
            count = 0
        if count >= expected:
            break
        time.sleep(0.05)
    return count, time.monotonic() - start


def ranges(ids) -> str:
    """Compress sorted ints into "a-b, c" form for readable reporting."""
    ids = sorted(ids)
    if not ids:
        return "-"
    out, start, prev = [], ids[0], ids[0]
    for i in ids[1:]:
        if i != prev + 1:
            out.append(f"{start}-{prev}" if start != prev else str(start))
            start = i
        prev = i
    out.append(f"{start}-{prev}" if start != prev else str(start))
    return ", ".join(out)


def stored_ids(port: int, session_id: str, prefix: str) -> set:
    ids, page = set(), 1
    while True:
        events = get_json(
            port, f"/api/sessions/{session_id}/events?page={page}&limit=500"
        )["events"]
        ids.update(e["event_id"] for e in events if e["event_id"].startswith(prefix))
        if len(events) < 500:
            return ids
        page += 1


def outage(before: int, during: int, max_queue_size: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="agentscope-res-") as tmp:
        server = ServerProcess(db_path=Path(tmp) / "res.db").start()
        port = server.port
        client = AgentScopeClient(
            host="127.0.0.1",
            port=port,
            session_name="outage",
            max_queue_size=max_queue_size,
        )
        try:
            for i in range(before):
                client.emit(make_event(f"before-{i}"))
            deadline = time.monotonic() + 10
            while client.session_id is None and time.monotonic() < deadline:
                time.sleep(0.01)
            session_id = client.session_id
            stored_before, _ = wait_for_count(port, session_id, before, 15)

            outage_start = time.monotonic()
            server.stop()
            for i in range(during):
                client.emit(make_event(f"during-{i}"))
                time.sleep(1.0 / max(during, 1))  # spread over ~1 s

            restart = time.monotonic()
            server.start()  # same port, same database file; waits for /health
            healthy = time.monotonic()
            expected = stored_before + min(during, max_queue_size)
            wait_for_count(port, session_id, expected, 60)
            delivered = time.monotonic()
            # Let any straggling retries land before reading the ids.
            time.sleep(0.5)
            during_ids = stored_ids(port, session_id, "during-")
        finally:
            client.stop()
            server.cleanup()

    return {
        "stored before": stored_before,
        "delivered": len(during_ids),
        "kept": ranges(int(e.split("-")[1]) for e in during_ids),
        "outage s": healthy - outage_start,
        "server start s": healthy - restart,
        "recovery s": delivered - healthy,
    }


SCENARIOS = [
    ("A: outage within buffer", 100, 300, 5000),
    ("B: outage overflows buffer", 100, 2000, 500),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=5)
    args = parser.parse_args()

    rows = []
    for label, before, during, buffer in SCENARIOS:
        runs = [outage(before, during, buffer) for _ in range(args.repeat)]
        for i, run in enumerate(runs, 1):
            print(
                f"{label} run {i}: delivered {run['delivered']}/{during}, "
                f"kept during-# {run['kept']}, outage {run['outage s']:.2f} s, "
                f"server start {run['server start s']:.2f} s, "
                f"recovery {run['recovery s']:.2f} s"
            )
        kept = sorted({r["kept"] for r in runs})
        rows.append(
            {
                "scenario": label,
                "runs": len(runs),
                "buffer": f"{buffer:,}",
                "sent during outage": f"{during:,}",
                "delivered after restart": int_range([r["delivered"] for r in runs]),
                "kept during-#": " / ".join(kept),
                "outage s": spread([r["outage s"] for r in runs], 2),
                "server start s": spread([r["server start s"] for r in runs], 2),
                "recovery s": spread([r["recovery s"] for r in runs], 2),
            }
        )

    print(f"\nMachine: {machine_info()}")
    print_table(
        f"Server outage and recovery, median (min–max) over {args.repeat} runs",
        rows,
        list(rows[0].keys()),
    )


if __name__ == "__main__":
    main()
