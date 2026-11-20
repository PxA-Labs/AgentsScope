# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Miscellaneous
- Build(deps): bump actions/setup-python from 7.0.0 to 7.1.0

## [agentscope-trace 0.1.0]

First release of the Python SDK on PyPI, as **`agentscope-trace`** (`pip install agentscope-trace`). The names `agentscope` and `agentscope-sdk` on PyPI belong to unrelated projects. This is a pre-1.0 release: the public API may still change between minor versions. The server and dashboard are not published to PyPI; run them from the repository or with Docker Compose, and note that the `agentscope start` command needs a repository checkout (run it from the repo root). The `[1.0.0]` entry below is an earlier project milestone, not an SDK version.

### Added
- **Core SDK** (from earlier development, published for the first time): the LangChain `AgentScopeCallback`, `patch_openai()`, the `@trace` / `@trace_llm` / `@trace_tool` / `@trace_retriever` decorators, per-call cost tracking with an optional `budget_limit_usd`, and the `langchain` and `tiktoken` extras.
- **Framework integrations:** CrewAI via its event bus, including Flows ([#292](https://github.com/PxA-Labs/AgentsScope/pull/292), [#338](https://github.com/PxA-Labs/AgentsScope/pull/338)); AutoGen through a traced model client and team run tracer ([#293](https://github.com/PxA-Labs/AgentsScope/pull/293)); LlamaIndex via its instrumentation API ([#295](https://github.com/PxA-Labs/AgentsScope/pull/295)). Install with the `crewai`, `autogen` and `llamaindex` extras.
- **Model SDK auto-instrumentation:** `patch_anthropic()`, `patch_gemini()` and `patch_all()` alongside `patch_openai()`, covering sync, async and streaming calls ([#288](https://github.com/PxA-Labs/AgentsScope/pull/288), [#341](https://github.com/PxA-Labs/AgentsScope/pull/341)). Install the SDKs with the `anthropic` and `gemini` extras, or bring your own.
- **Authentication and TLS:** `api_key=` (or `AGENTSCOPE_API_KEY`) and `base_url=` / `secure=True` for protected or remote servers ([#287](https://github.com/PxA-Labs/AgentsScope/pull/287)).
- **Graceful shutdown:** buffered events are delivered at exit even if `stop()` is never called, bounded by `shutdown_timeout` (an `AgentScopeClient` argument, 5 s by default) ([#296](https://github.com/PxA-Labs/AgentsScope/pull/296)).
- `max_queue_size` on `AgentScopeClient`, plus documented performance figures in `docs/PERFORMANCE.md` ([#291](https://github.com/PxA-Labs/AgentsScope/pull/291)).

### Fixed
- `budget_limit_usd` now actually stops the LangChain run; before, LangChain swallowed `BudgetExceededError` ([#317](https://github.com/PxA-Labs/AgentsScope/pull/317)).
- `stop()` no longer hangs when the offline buffer is full ([#290](https://github.com/PxA-Labs/AgentsScope/pull/290)), and neither `stop()` nor the exit-time flush waits out its timeout after the server rejects the API key ([#340](https://github.com/PxA-Labs/AgentsScope/pull/340)).
- Cancelling a traced AutoGen run stops the team instead of letting it run on ([#339](https://github.com/PxA-Labs/AgentsScope/pull/339)).

### Changed
- **Requires Python 3.11+** ([#285](https://github.com/PxA-Labs/AgentsScope/pull/285)).
- **The import package is `agentscope_trace`** ([#335](https://github.com/PxA-Labs/AgentsScope/pull/335)); `import agentscope` keeps working through a deprecated shim, see below.
- PEP 639 licence metadata (`License-Expression: Apache-2.0`) ([#282](https://github.com/PxA-Labs/AgentsScope/pull/282)).

### Server and dashboard (in the repository, not on PyPI)
CSV export ([#286](https://github.com/PxA-Labs/AgentsScope/pull/286)); optional API-key auth for REST and WebSocket ([#287](https://github.com/PxA-Labs/AgentsScope/pull/287)); no more lost events when several SDK clients write to SQLite at once, with each event and its session totals stored atomically ([#324](https://github.com/PxA-Labs/AgentsScope/pull/324), [#333](https://github.com/PxA-Labs/AgentsScope/pull/333)); the dashboard split into components with Vitest and Playwright tests, fixing dropped live events ([#332](https://github.com/PxA-Labs/AgentsScope/pull/332)); React 19, ESLint 9 and Tailwind CSS 4 ([#320](https://github.com/PxA-Labs/AgentsScope/pull/320), [#284](https://github.com/PxA-Labs/AgentsScope/pull/284), [#334](https://github.com/PxA-Labs/AgentsScope/pull/334)).

### Import package renamed to `agentscope_trace` ([#297](https://github.com/PxA-Labs/AgentsScope/issues/297))

The distribution name (`agentscope-trace`) and the `agentscope` CLI command are unchanged; only the Python import name moves.

- **Migrate**: `s/from agentscope/from agentscope_trace/` and `s/import agentscope/import agentscope_trace/`, plus `agentscope.<name>` attribute uses and module-name strings (`monkeypatch.setattr("agentscope....")` targets):
  ```bash
  perl -pi -e 's/\b(from|import) agentscope\b/$1 agentscope_trace/g; 1 while s/^(\s*import\s[^#]*,\s*)agentscope\b/$1agentscope_trace/; s/(?<![\w.\/@-])agentscope(?=\.\w)/agentscope_trace/g' *.py
  ```
  Review the diff: it can also rewrite a bare `agentscope.<host>` string or imports of agentscope-ai's unrelated `agentscope`. Alternatively, `import agentscope_trace as agentscope` keeps `agentscope.<name>` uses working. Logging config must be updated by hand: loggers are now `agentscope_trace.*`. See [packages/sdk/README.md](packages/sdk/README.md#migrating-from-import-agentscope).
- **Compatibility**: `import agentscope` and `agentscope.<submodule>` imports keep working through a deprecated shim that emits one `DeprecationWarning`. It aliases the same module objects, so old and new imports can be mixed during migration. Import the package once at startup, before starting threads (a thread's first import of `agentscope.<name>` can fail while another thread's first `import agentscope` is still running).
- **Deprecation timeline**: the shim ships in 0.1.0 and stays for at least one further minor release; it is removed in a later minor release (first shipped in 0.1.0, kept through 0.2.x, removed in 0.3.0 at the earliest).
- **Why**: the shim is the one file that still clashes with the unrelated `agentscope` package on PyPI (agentscope-ai). Until it is removed, the two cannot be installed in the same environment.
- **Contributors**: an editable install made before the rename only maps `agentscope`, so both import names fail until you re-run `make setup-sdk` (or `pip install -e packages/sdk`).

## [1.0.0] - 2026-08-10

### Added
- Created the core Next.js developer dashboard UI package (`packages/ui`).
- Implemented dual-pool WebSocket manager and REST API router endpoints on the server.
- Built SQL-based pagination for session telemetry event queries.
- Added database session retention and pruning policies (`RETENTION_DAYS`, `MAX_SESSIONS`).
- Integrated timezone-aware ISO-8601 formatting for standard UTC timestamps.
- Added support for Claude 3 (Haiku, Sonnet, Opus) and Gemini 1.5 (Pro, Flash) model price resolutions.
- Implemented custom environment pricing overrides via `AGENTSCOPE_CUSTOM_PRICING` and programmatic configuration overrides.
- Covered all trace decorator client and websocket emissions in try-except statements to guarantee non-intrusive operations.
- Added detailed step-by-step installation guides and verification scripts in `docs/DEVELOPMENT.md` and runnable integration examples.
