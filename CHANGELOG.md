# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Fixed
- **sdk**: Don't mark an over-budget session completed
- **sdk**: Make budget_limit_usd actually stop the LangChain run

### Documentation
- Spell out the budget behaviour for each kind of run
- The server reads environment variables, not a .env file
- Describe what budget_limit_usd actually does
- **design**: Mark implemented future-architecture items
- **schema**: Document PostgreSQL support and graph_update WS messages
- **server**: Document API routes, storage backends and configuration
- **sdk**: Document install extras, OpenAI patching, decorators and budgets
- **prd**: Record shipped post-MVP work and current constraints
- **readme**: Update structure, tech stack and FAQ
- **readme**: Document the environment variables the server reads
- **readme**: List shipped features and link roadmap to issues
- **readme**: Fix SDK install command

### Tests
- **sdk**: A sync run whose last call crosses the budget ends failed
- **sdk**: Drive budget enforcement through real LangChain runs

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
