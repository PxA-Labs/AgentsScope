# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **ui**: Name CSV downloads with the server's Content-Disposition filename
- **ui**: Add CSV option to session export
- **server**: Stream CSV from the session export endpoint
- **server**: Add CSV serializer for session events

### Documentation
- **server**: Note that a CSV export holds a DB connection while streaming
- **schema**: Document JSON and CSV session export formats

### Performance
- **server**: Send the CSV export one chunk per batch, not per row

### Tests
- **server**: Catch an early db.close() during CSV streaming
- **server**: Seed CSV export test sessions relative to now
- **server**: Cover CSV export over HTTP, including streaming

### Style
- **server**: Bind the wrapped close() in the CSV lifetime test
- **server**: Spell the remaining CSV BOM in the API tests as an escape
- **server**: Spell the CSV BOM as an escape in tests

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
