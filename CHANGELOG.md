# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **cli**: Explain how to get the server when run from a pip install

### Documentation
- Add RELEASING.md for the agentscope-trace release process

### CI/CD
- **release**: Only publish tags on main, mark pre-releases, serialise runs
- **release**: Let a re-tag of the same version get past TestPyPI
- **release**: Publish agentscope-trace to PyPI on version tags
- **release**: Add tag/version consistency check

### Miscellaneous
- Build(sdk): publish as agentscope-trace and single-source the version

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
