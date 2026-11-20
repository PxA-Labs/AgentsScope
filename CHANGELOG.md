# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **sdk**: Add LlamaIndex integration via the instrumentation API

### Fixed
- **sdk**: Fold LlamaIndex LLM calls made inside an async stream into one node
- **sdk**: Never block on the LlamaIndex mapper lock from a stream finalizer
- **sdk**: Stop doubling streamed text when LlamaIndex folds a nested call
- **sdk**: Switch LlamaIndex client when instrumenting again with one
- **sdk**: Cap open LlamaIndex nodes and document FIFO eviction
- **sdk**: Close LlamaIndex nodes that never get an end event
- **sdk**: Resolve the global client per event in the LlamaIndex integration

### Documentation
- **sdk**: Note that LlamaIndex async streams on CustomLLM are one node
- **sdk**: Describe LlamaIndex stream closing and client switching
- **sdk**: Document the LlamaIndex integration and add an offline example

### Tests
- **sdk**: Unit-test LlamaIndex event mapping without LlamaIndex
- **sdk**: Exercise the LlamaIndex integration with real query engines

### Miscellaneous
- Build(sdk): add llamaindex extra and a Python 3.11 CI job

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
