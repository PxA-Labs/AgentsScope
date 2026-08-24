# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-08-24

### Miscellaneous
- Build(deps): update uvicorn requirement in /packages/server

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
