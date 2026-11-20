# AgentScope Observability Server

The backend hub for AgentScope. It's a FastAPI server that acts as the central telemetry store: it consumes telemetry streams from the SDK over WebSockets and serves them over a REST API and live WebSocket feeds to the Next.js dashboard.

## Features

- **Dual-pool WebSocket manager**: a single `/ws` endpoint handles SDK ingestion (`?client_type=sdk`) and UI subscriptions (`?client_type=ui&session_id=...`) concurrently, including live DAG graph deltas.
- **Storage backends**: SQLite by default (WAL mode, zero configuration), or PostgreSQL via `asyncpg` with `DATABASE_URL=postgresql+asyncpg://...`.
- **Cost accounting**: token and USD cost aggregation per session from the shared `pricing.json` table (override with `AGENTSCOPE_PRICING_FILE`).
- **Retention and pruning**: a periodic job deletes sessions by age (`AGENTSCOPE_RETENTION_DAYS`) or count (`AGENTSCOPE_MAX_SESSIONS`) every `AGENTSCOPE_PRUNE_INTERVAL_SECONDS`, then vacuums SQLite.
- **Export / import**: round-trip a session and all its events as JSON.
- **Session memories**: optional [Mem0](https://mem0.ai) integration (`MEM0_API_KEY`) for tagged, searchable session memories.

## API

All REST routes are under `/api`. Interactive docs are available at `/docs` while the server is running.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `GET` / `POST` | `/api/sessions` | List sessions (paginated) / create a session |
| `GET` / `PATCH` / `DELETE` | `/api/sessions/{session_id}` | Read, update status, or delete a session |
| `GET` | `/api/sessions/{session_id}/graph` | DAG nodes and edges |
| `GET` | `/api/sessions/{session_id}/stats` | Aggregated tokens, cost, latency and agents |
| `GET` | `/api/sessions/{session_id}/export` | Export a session and its events as JSON |
| `POST` | `/api/sessions/import` | Import a JSON export |
| `GET` | `/api/sessions/{session_id}/events` | Paginated events |
| `GET` | `/api/sessions/{session_id}/events/{event_id}` | A single event |
| `GET` / `POST` / `DELETE` | `/api/sessions/{session_id}/memories` | List, add, or delete all memories (Mem0) |
| `POST` | `/api/sessions/{session_id}/memories/search` | Semantic memory search |
| `PUT` / `DELETE` | `/api/sessions/{session_id}/memories/{memory_id}` | Update or delete a memory |
| `WS` | `/ws` | Event ingestion (SDK) and live updates (UI) |

## Configuration

All settings are environment variables. See [`.env.example`](.env.example) and the [root README](../../README.md#configuration) for the full table.

## Dev Setup & Running

```bash
pip install -r packages/server/requirements.txt -r packages/server/requirements-dev.txt
cd packages/server && uvicorn main:app --host 127.0.0.1 --port 8765 --reload   # or: make run-server
pytest packages/server/tests
```

For more detail, see the [Development Setup Guide](../../docs/DEVELOPMENT.md).
