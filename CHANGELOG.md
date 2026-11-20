# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Fixed
- **sdk**: Stop the AutoGen team when the traced run is cancelled (#326)

### Documentation
- Describe how AutoGen run cancellation is traced (#326)

### Tests
- **sdk**: Reproduce AutoGen teams running on after cancellation (#326)

## Upcoming: SDK import package renamed to `agentscope_trace` ([#297](https://github.com/PxA-Labs/AgentsScope/issues/297))

Migration notes for the next `agentscope-trace` release. The distribution name (`agentscope-trace`) and the `agentscope` CLI command are unchanged; only the Python import name moves.

- **Migrate**: `s/from agentscope/from agentscope_trace/` and `s/import agentscope/import agentscope_trace/`, plus `agentscope.<name>` attribute uses and module-name strings (`monkeypatch.setattr("agentscope....")` targets):
  ```bash
  perl -pi -e 's/\b(from|import) agentscope\b/$1 agentscope_trace/g; 1 while s/^(\s*import\s[^#]*,\s*)agentscope\b/$1agentscope_trace/; s/(?<![\w.\/@-])agentscope(?=\.\w)/agentscope_trace/g' *.py
  ```
  Review the diff: it can also rewrite a bare `agentscope.<host>` string or imports of agentscope-ai's unrelated `agentscope`. Alternatively, `import agentscope_trace as agentscope` keeps `agentscope.<name>` uses working. Logging config must be updated by hand: loggers are now `agentscope_trace.*`. See [packages/sdk/README.md](packages/sdk/README.md#migrating-from-import-agentscope).
- **Compatibility**: `import agentscope` and `agentscope.<submodule>` imports keep working through a deprecated shim that emits one `DeprecationWarning`. It aliases the same module objects, so old and new imports can be mixed during migration. Import the package once at startup, before starting threads (a thread's first import of `agentscope.<name>` can fail while another thread's first `import agentscope` is still running).
- **Deprecation timeline**: the shim ships in the first release with the rename and stays for at least one further minor release; it is removed in a later minor release (first shipped in 0.N.0, kept through 0.N+1.x, removed in 0.N+2.0 at the earliest).
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
