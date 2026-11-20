# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **sdk**: Make the offline event buffer size configurable

### Documentation
- **perf**: Don't overstate the latency tail
- Note that dashboard timings predate the React bump
- **sdk**: Mention the max_queue_size option in the SDK README
- Re-measure performance against PRD targets after #296
- Record measured performance against PRD targets

### Tests
- **sdk**: Drop the #289 workaround from the perf gate, fix headroom
- **bench**: Add a cold-cache mode to the time-to-value script
- **bench**: Time outage recovery from server health, repeat runs
- **bench**: Repeat the end-to-end latency sweep and report spread
- **bench**: Pace the server-up emit() benchmark and report drops
- **sdk**: Add CI regression gate for emit() and @trace overhead
- **bench**: Add time-to-value script (clone to first stored event)
- **bench**: Measure delivery and recovery across a server outage
- **bench**: Measure end-to-end emit-to-dashboard latency
- **bench**: Add benchmark harness and SDK overhead benchmark

### CI/CD
- Fail the benchmark job when a benchmark fails
- Add make bench / make ttv and a weekly benchmark workflow

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
