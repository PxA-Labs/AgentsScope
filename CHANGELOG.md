# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Documentation
- Update the minimum Python version to 3.11

### Tests
- **ci**: Parse workflows as YAML in the Python-support guard
- **ci**: Keep CI Python versions aligned with requires-python

### CI/CD
- Test the server on Python 3.14, the version its image runs
- Test the SDK and server on Python 3.11, 3.12 and 3.13

### Miscellaneous
- Build(deps): require SQLAlchemy 2.1 and websockets 17 on the server
- Build: require Python 3.11+

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
