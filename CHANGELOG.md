# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-09-14

### Fixed
- **ci**: Resolve invalid action refs in auto-changelog and scorecard workflows
- Harden pricing artifacts and test isolation
- **sdk,server**: Unify model pricing tables

### Maintenance
- **security**: Implement OpenSSF standards, Scorecard workflow, and Pre-PR quality suite

### Miscellaneous
- Build(deps): bump github/codeql-action/init from 4.37.9 to 4.38.0
- Build(deps): bump actions/upload-artifact from 4.6.1 to 7.0.1
- Build(deps): bump github/codeql-action/upload-sarif
- Build(deps-dev): update ruff requirement in /packages/sdk
- Build(deps): bump swr from 2.5.0 to 2.5.1 in /packages/ui
- Build(deps-dev): update langchain-core requirement in /packages/sdk
- Build(deps): bump lucide-react from 1.40.0 to 1.44.0 in /packages/ui
- Build(deps): bump github/codeql-action/init from 3.28.10 to 4.37.9
- Build(deps): bump actions/github-script from 7.0.1 to 9.0.0
- Build(deps-dev): update ruff requirement in /packages/sdk
- Build(deps): bump lucide-react from 1.29.0 to 1.40.0 in /packages/ui
- Build(deps): update pydantic requirement in /packages/server
- Build(deps-dev): bump @types/node from 26.4.0 to 26.4.1 in /packages/ui
- Build(deps): update mem0ai requirement in /packages/server
- Build(deps): update pydantic requirement in /packages/sdk
- Build(deps): bump actions/setup-python from 5.4.0 to 7.0.0
- Build(deps): bump actions/setup-node from 4.0.3 to 7.0.0
- Build(deps): bump github/codeql-action/upload-sarif
- Build(deps): bump next from 16.3.1 to 16.3.3 in /packages/ui
- Build(deps-dev): update ruff requirement in /packages/sdk
- Build(deps-dev): bump @types/node from 26.2.0 to 26.4.0 in /packages/ui
- Build(deps-dev): update langchain-core requirement in /packages/sdk
- Build(deps): update mem0ai requirement in /packages/server
- Build(deps): bump actions/labeler from 5.0.0 to 7.0.0
- Build(deps): bump actions/checkout from 4.2.2 to 7.0.1
- Potential fix for pull request finding 'CodeQL / Log Injection'
- Potential fix for pull request finding 'CodeQL / Log Injection'

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
