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

## Styling

The dashboard uses Tailwind CSS 4 through the `@tailwindcss/postcss` plugin (`postcss.config.js`). There is no `tailwind.config.js`: the theme lives in `app/globals.css`, in `@theme` blocks next to the `:root` colour variables. Tailwind scans the package for class names on its own and skips `tests/`.

`app/globals.css` also keeps a few Tailwind 3 defaults so the look did not change in the upgrade (#330): the v3 sRGB palette for the colour families we use, fixed line heights for the `text-*` sizes, gray borders and placeholders, and pointer cursors on buttons. Tailwind 4 needs Safari 16.4+, Chrome 111+ or Firefox 128+.

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
