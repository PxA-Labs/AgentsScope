# AgentScope Developer Dashboard UI

The Next.js/Tailwind CSS frontend for AgentScope. It displays real-time agent execution sessions, trace lists, metrics charts, and agent call hierarchy graphs.

## Features

- **Real-time Live Ingestion**: Streams events instantly from the FastAPI server using WebSockets.
- **State Management**: Uses Zustand to cache session events and update layouts.
- **Metric Grids**: Real-time charts of tokens consumed, durations, latencies, and costs.
- **Interactive Call Feed**: Chronological nested listings of event payloads with details.

## Dev Setup & Running

For instructions on installing node modules and launching the dev server, please refer to the main [Development Setup Guide](../../docs/DEVELOPMENT.md).
