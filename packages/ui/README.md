# AgentScope Developer Dashboard UI

The Next.js/Tailwind CSS frontend for AgentScope. It displays real-time agent execution sessions, trace lists, metrics charts, and agent call hierarchy graphs.

## Features

- **Real-time Live Ingestion**: Streams events instantly from the FastAPI server using WebSockets.
- **State Management**: Uses Zustand to cache session events and update layouts.
- **Metric Grids**: Real-time charts of tokens consumed, durations, latencies, and costs.
- **Interactive Call Feed**: Chronological nested listings of event payloads with details.

## Dev Setup & Running

For instructions on installing node modules and launching the dev server, please refer to the main [Development Setup Guide](../../docs/DEVELOPMENT.md).

## Code Layout

- `app/page.tsx` composes the dashboard; `app/diff/page.tsx` is the session comparison page.
- `components/` holds the UI pieces: `SessionList`, `SessionHeader`, `ConnectionStatus`, `ExportImportControls`, `StatsPanel`, `EventFeed`, `EventInspector`, `AgentGraph`, `MemoriesPanel`, `AuthBanner` and the diff viewers.
- `hooks/` holds data access and live updates: `useSessions` (list polling), `useSessionDetail` (events, graph, stats), `useLiveEvents` (the only WebSocket, with reconnect backoff), `useMemories`, `useSessionImport` and `useUnauthorized`.
- `lib/api.ts` is the typed REST client (API-key auth, export and import helpers); `store/sessionStore.ts` is the Zustand store.

## Tests

Run these from `packages/ui`:

```bash
npm test                  # Vitest + React Testing Library + msw unit tests
npm run test:coverage     # same, failing below 60% line coverage on store/ and lib/
npx playwright install --only-shell chromium   # once, for the E2E test
npm run test:e2e          # Playwright smoke test against the real server
```

The E2E test starts the FastAPI server from `packages/server` (with the Python in `E2E_PYTHON`, default `python3`, which needs `packages/server/requirements.txt`) on a temporary SQLite database, builds and starts the dashboard, and checks that a new session and its live events show up. Ports default to 8765 and 3000; set `E2E_API_PORT` and `E2E_UI_PORT` to use others. The unit tests need Node.js 22.22+ or 24.15+ (jsdom 31's minimum); running and building the dashboard only needs Node.js 20.9+. `make test-ui` runs lint, type-check, unit tests and build; the E2E test is opt-in with `make test-ui-e2e`.

`make test-ui` runs lint, type-check, unit tests, build and the E2E test.
