# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **sdk**: Add AutoGen integration (model client wrapper + run tracer)

### Fixed
- **sdk**: Stop the AutoGen team on early close and close the run last
- **sdk**: Treat a cancelled AutoGen stream finalizer as an early close
- **sdk**: Make the traced AutoGen model client serializable
- **sdk**: Start a new AutoGen turn for each agent response
- **sdk**: Resolve the global client per event in the AutoGen integration
- **sdk**: Close AutoGen runs cleanly when the consumer stops early

### Documentation
- **sdk**: Describe what early close does to an AutoGen team
- **sdk**: Describe AutoGen early close, turns and reconfiguration
- **sdk**: Document the AutoGen integration and add an example

### Tests
- **sdk**: Rename AutoGen turn-grouping test to match its behaviour
- **sdk**: Unit-test AutoGen run tracer edge cases without AutoGen
- **sdk**: Exercise the AutoGen integration with real teams

### Miscellaneous
- Build(sdk): add autogen extra and run AutoGen tests in CI

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
