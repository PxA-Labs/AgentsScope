# AgentScope Project Rules & Conventions

This document outlines the core principles, coding standards, architectural guidelines, and processes for the AgentScope project. Adhering to these rules ensures consistency, high code quality, and maintainability across the Python SDK, FastAPI Server, and Next.js UI modules.

## 1. Project Philosophy

- **Developer experience first**: AgentScope should require only 2 lines to instrument and offer zero configuration to get started.
- **Local-first**: No cloud dependencies and no accounts required. Everything runs locally.
- **Minimal dependencies**: Each module should have the fewest possible dependencies to reduce bloat and compatibility issues.
- **Non-blocking SDK**: The SDK must **NEVER** block the agent pipeline.
- **Unidirectional Data Flow**: Data flows strictly in one direction: SDK → Server → UI.

## 2. Code Style & Formatting

### Python (SDK + Server)

- **Version**: Python 3.10+ required.
- **Formatter**: `black` with default settings (line length 88).
- **Linter**: `ruff` with pyflakes + pycodestyle + isort enabled.
- **Type hints**: Required on all public functions, optional (but encouraged) on internal functions.
- **Docstrings**: Google style is required on all public classes and functions.
- **Imports**: Formatted using `isort` with a black-compatible profile. Order: stdlib → third-party → local.
- **Naming Conventions**:
  - Functions/Variables: `snake_case`
  - Classes: `PascalCase`
  - Constants: `UPPER_SNAKE`
- **Standard Library usage**:
  - Prefer `pathlib.Path` over `os.path`.
  - Use f-strings over `.format()` or `%` formatting.
- **Frameworks**:
  - Use Pydantic v2 models for all data validation.
  - Use SQLAlchemy 2.0 style (avoid legacy 1.x patterns).
- **Control Flow & Error Handling**:
  - Prefer async functions for I/O-bound operations.
  - No bare `except:` — always catch specific exceptions.
  - Use the built-in `logging` module for all output; never use `print()`.

### TypeScript (UI)

- **Language**: TypeScript strict mode is required.
- **Formatter**: Prettier (default configuration).
- **Linter**: ESLint with Next.js configuration.
- **Component Pattern**: Functional components with hooks only. No class components.
- **Types/Props**: Define props as TypeScript interfaces (no inline types).
- **Naming Conventions**:
  - Variables/Functions: `camelCase`
  - Components/Types: `PascalCase`
  - Constants: `UPPER_SNAKE`
- **File Naming**:
  - Components: PascalCase (e.g., `AgentGraph.tsx`)
  - Hooks: camelCase (e.g., `useWebSocket.ts`)
  - Utilities: camelCase (e.g., `api.ts`)
- **Declarations & Exports**:
  - Use `const` by default. Use `let` only when reassignment is needed. Never use `var`.
  - Prefer named exports over default exports.
- **Styling**: Tailwind utility classes only. Use `shadcn/ui` for primitives. **No** MUI, Chakra, or Ant Design.

## 3. Architecture Rules

- **Data Flow**: SDK → Server → UI is the ONLY allowed data flow direction. The UI never writes data to the server (with the exception of DELETE operations for session cleanup).
- **Identifiers**: Use LangChain's `run_id` directly as `event_id`. Never generate new UUIDs for events.
- **Layout Computation**: The server computes the graph layout using `dagre`, not the UI.
- **SDK Telemetry**: All WebSocket transmissions in the SDK must be fire-and-forget, running in a background task or thread.
- **Token Costs**: Estimate token cost from LLM response metadata *only* when available; do not estimate when unavailable (display '—').
- **Database**: Use SQLite with WAL mode (`PRAGMA journal_mode=WAL`).
- **Graph UI**: Use React Flow for graph visualization, not D3.

## 4. Git Conventions

- **Branch Naming**:
  - `feature/short-description`
  - `fix/short-description`
  - `docs/short-description`
- **Commit Messages**: Follow the [Conventional Commits](https://www.conventionalcommits.org/) format.
  - Examples:
    - `feat: add real-time event feed component`
    - `fix: handle WebSocket reconnection on network drop`
    - `docs: add integration guide for LangChain`
    - `chore: update dependencies`
    - `refactor: simplify event broadcasting logic`
    - `test: add unit tests for session router`
- **Pull Requests**: PR titles must follow the same commit message convention.
- **Merging**: Use Squash merge to main.
- **Main Branch**: The `main` branch must remain in a consistently deployable state.

## 5. Testing Rules

### Python
- **Framework**: `pytest`
- **Coverage**: Minimum 80% for SDK, 70% for Server.
- **Structure**: Place tests in a `tests/` directory within each package.
- **Naming**: `test_<function_name>_<scenario>`
- **Mocking**: Mock all external dependencies (e.g., WebSockets, database).
- **Async**: Use `pytest-asyncio` for async testing.
- **Fixtures**: Define fixtures in `conftest.py`.

### TypeScript
- **Framework**: Jest + React Testing Library.
- **Scope**: Test component rendering and user interactions.
- **Mocking**: Mock WebSocket connections and API calls.
- **Structure**: Test files must be colocated with the source code (e.g., `*.test.tsx` or `*.test.ts`).

## 6. Dependency Rules

| Module | Allowed/Expected Dependencies |
| ------ | ----------------------------- |
| **SDK** | `websockets`, `pydantic`. `langchain-core` as an optional extra. |
| **Server**| `fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `websockets`, `python-dotenv` |
| **UI** | `next`, `react`, `reactflow`, `recharts`, `zustand`, `swr`, `tailwindcss` |

- **General Rule**: No dependency should be added without strong justification.
- **Versioning**: Pin major versions but allow minor/patch updates.
- **Maintenance**: Review and update dependencies on a monthly basis.

## 7. Error Handling Rules

- **SDK**: NEVER raise exceptions into the agent pipeline. Catch all errors, log a warning, and continue execution.
- **Server**: Return appropriate HTTP status codes (e.g., 400, 404, 422, 500) complete with descriptive error bodies.
- **UI**: Always display user-friendly error states (never blank screens). Use toast notifications for transient errors.
- **Logging**: All errors across the stack must be logged with sufficient context (e.g., `session_id`, `event_id`).

## 8. Security Rules (v1)

- **Authentication**: None required (this is a local dev tool).
- **CORS**: Allow all origins (for local development only).
- **Data Privacy**: No PII storage by design. Note that events contain LLM prompts/completions which may inherently contain user data.
- **File System**: SQLite file permissions should be restricted to user-only read/write.
- **Network**: No external network calls from the server or UI (except to localhost).

## 9. Documentation Rules

- **Code Comments**: All public APIs must have docstrings (Python) or JSDoc (TypeScript).
- **Readmes**:
  - The root `README.md` must include a 5-minute quickstart guide.
  - Each module (`sdk`, `server`, `ui`) must have its own detailed `README.md`.
- **Changelog**: `CHANGELOG.md` must be updated with every release.
- **Examples**: The `examples/` directory must contain code that is runnable with minimal setup.

## 10. Performance Rules

- **SDK Telemetry**: SDK callback methods must return in **< 1ms** (employ async fire-and-forget).
- **Server Throughput**: Server event ingestion must be capable of handling **1000 events/second**.
- **UI Rendering**: The UI must be able to render up to **10,000 events per session** without frame drops or jank.
- **Graph Layout**: Graph layout computation must complete in **< 2 seconds for 500 nodes**.
- **API Latency**: REST API responses must complete in **< 200ms** for typical queries.

## 11. Release Process

- **Versioning Strategy**: Use Semantic Versioning (`MAJOR.MINOR.PATCH`).
  - Use `v0.x.x` during initial development.
- **Releases**: Tag releases on GitHub.
- **Distribution**:
  - Publish the SDK to PyPI.
  - Docker images should be tagged with the exact version.
- **Changelog**: `CHANGELOG.md` must be updated prior to every release.
