# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **sdk**: Record standalone CrewAI Agent.kickoff() runs
- **sdk**: Add CrewAI integration via the CrewAI event bus

### Fixed
- **sdk**: Let only the top-level CrewAI crew set the session status
- **sdk**: Keep CrewAI listener memory flat across kickoffs
- **sdk**: Deliver pending CrewAI events when the listener closes

### Documentation
- **sdk**: Update CrewAI docs for session status, lite agents and memory
- **sdk**: Document the CrewAI integration and add an example

### Tests
- **sdk**: Run AgentScopeCrewAIListener against a real CrewAI crew
- **sdk**: Unit-test CrewAI event mapping without CrewAI

### Miscellaneous
- Build(sdk): raise the pydantic floor to 2.9
- Build(sdk): add crewai extra and a CI job for the CrewAI tests
- Build(sdk): relax pydantic floor to the tested 2.7.4

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
