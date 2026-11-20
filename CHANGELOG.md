# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Fixed
- **sdk**: Keep events stop() could not deliver; document what happens
- **sdk**: Run executor calls inline when threads are refused at exit
- **sdk**: Clear running even if the sender thread fails before its loop
- **sdk**: One exit hook for all clients, stopping them in parallel
- **sdk**: Don't report stopped while the old sender thread still runs
- **sdk**: Wake the idle sender on emit and stop instead of polling
- **sdk**: Flush at exit without the default executor
- **sdk**: Exit cleanly and deliver buffered events on shutdown

### Tests
- **sdk**: Stopped clients are collectable and exit stops clients in parallel
- **sdk**: Restart after a timed-out stop() never runs two senders
- **sdk**: Idle-sender latency and stop() waking a reconnect backoff
- **sdk**: Short script with no sleep and no stop() delivers and exits fast
- **server**: End-to-end SDK shutdown against a real uvicorn server
- **sdk**: Cover graceful shutdown in-process and in real interpreters

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
