# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **sdk**: Trace anthropic messages.parse()
- **sdk**: Export provider patches and add patch_all / unpatch_all
- **sdk**: Add patch_gemini / unpatch_gemini for google-genai
- **sdk**: Add patch_anthropic / unpatch_anthropic
- **sdk**: Let provider adapters attach usage details to llm_end

### Fixed
- **sdk**: Normalise Vertex AI model resource names for Gemini
- **sdk**: Count Gemini thought tokens as completion tokens
- **sdk**: Start the anthropic stream() trace when the with block is entered
- **sdk**: Record anthropic stream() as llm_end when the caller raises

### Documentation
- **sdk**: Correct provider streaming claims and add known limitations
- **sdk**: Document provider auto-instrumentation and add examples

### Refactor
- **sdk**: Extract provider-agnostic LLM tracing into providers/_base

### Tests
- **sdk**: Make the Gemini nesting test fail when nothing is traced
- **sdk**: Cover patch_all, unpatch_all and lazy SDK imports
- **sdk**: Exercise patch_gemini against the real SDK
- **sdk**: Exercise patch_anthropic against the real SDK

### Miscellaneous
- Build(sdk): add anthropic and gemini extras; test them in CI

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
