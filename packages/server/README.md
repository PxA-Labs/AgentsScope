# AgentScope Observability Server

The backend hub for AgentScope. It exposes a FastAPI server that acts as a central telemetry store, consuming telemetry streams via WebSockets and serving them via REST API to the React-based developer dashboard UI.

## Features

- **Double-pool WebSocket Manager**: Handles SDK telemetry event connections and UI client event subscription streams concurrently.
- **SQLite Database Backend**: Persists sessions, events, and metrics locally.
- **Automatic Database Pruning**: Periodically prunes expired or excess sessions according to configured policies (`RETENTION_DAYS`, `MAX_SESSIONS`).
- **REST Endpoints**: Provides paginated sessions, events, and layout DAG graphs.

## Dev Setup & Running

For instructions on setting up python environment and starting the server, please refer to the main [Development Setup Guide](../../docs/DEVELOPMENT.md).
