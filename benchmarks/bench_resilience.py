"""SDK behaviour across a server outage.

Scenario A: the server is stopped mid-session while the SDK keeps emitting,
then restarted on the same port and database. Counts how many events arrive
and how long recovery takes.

Scenario B: same, but the outage produces more events than the SDK buffer
holds (max_queue_size), showing the drop-oldest policy.

Run: python benchmarks/bench_resilience.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _harness import ServerProcess, count_events, get_json, make_event, print_table
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
        time.sleep(0.25)
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


def drain(client: AgentScopeClient) -> None:
    # Work around #289 (stop() blocks on a full buffer) on unfixed SDKs.
    while not client.queue.empty():
        try:
            client.queue.get_nowait()
        except Exception:
            break


def outage(label: str, before: int, during: int, max_queue_size: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="agentscope-res-") as tmp:
        server = ServerProcess(db_path=Path(tmp) / "res.db").start()
        port = server.port
        client = AgentScopeClient(
            host="127.0.0.1",
            port=port,
            session_name=label,
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

            server.stop()
            for i in range(during):
                client.emit(make_event(f"during-{i}"))
                time.sleep(1.0 / max(during, 1))  # spread over ~1 s

            restarted = time.monotonic()
            server.start()  # same port, same database file
            expected = stored_before + min(during, max_queue_size)
            stored_after, _ = wait_for_count(port, session_id, expected, 60)
            recovery_s = time.monotonic() - restarted

            during_ids = {
                e["event_id"]
                for e in get_json(
                    port, f"/api/sessions/{session_id}/events?limit=1000"
                )["events"]
                if e["event_id"].startswith("during-")
            }
            kept = ranges(int(e.split("-")[1]) for e in during_ids)
        finally:
            drain(client)
            client.stop()
            server.cleanup()

    return {
        "scenario": label,
        "buffer": max_queue_size,
        "sent before": before,
        "stored before": stored_before,
        "sent during outage": during,
        "delivered after restart": len(during_ids),
        "kept during-#": kept,
        "recovery s": round(recovery_s, 2),
    }


def main() -> None:
    rows = [
        outage("A: outage within buffer", before=100, during=300, max_queue_size=5000),
        outage(
            "B: outage overflows buffer", before=100, during=2000, max_queue_size=500
        ),
    ]
    print_table(
        "Server outage and recovery",
        rows,
        [
            "scenario",
            "buffer",
            "sent before",
            "stored before",
            "sent during outage",
            "delivered after restart",
            "kept during-#",
            "recovery s",
        ],
    )


if __name__ == "__main__":
    main()
