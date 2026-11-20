# Changelog

All notable changes to the **AgentScope** project will be documented in this file.

## [Unreleased] - 2026-11-20

### Added
- **ui**: Prompt for an API key when the server requires one
- **ui**: Attach API key to REST calls and WebSockets
- **sdk**: Send API key to servers with auth enabled
- **server**: Enforce optional API-key auth on /api and /ws
- **server**: Add optional API-key auth helpers

### Fixed
- **sdk**: Don't forward the API key when a REST call is redirected
- **server**: Avoid CodeQL weak-password-hashing false positive
- **server**: Clear CodeQL false positives in auth logging and comparison
- **sdk**: Back off to the maximum after a 4401 close
- **sdk**: Support https/wss so the API key need not travel in cleartext
- **ui**: Stop polling sessions once the server rejects the API key
- **server**: Rate-limit rejected-credential log lines per client
- **server**: Enforce API-key auth in ASGI middleware before routing
- **server**: Validate API-key configuration at startup
- **server**: Stop splitting AGENTSCOPE_API_KEY and compare key digests
- **sdk**: Make the 401 hint a literal to clear CodeQL false positive

### Documentation
- **auth**: Describe the SDK's retry backoff accurately
- Describe the HMAC comparison digest
- Document TLS in the SDK, the key policy and middleware enforcement
- Document optional API-key authentication

### Tests
- **sdk**: The API key must not follow a redirected REST call
- **server**: Check auth on every registered route, not a fixed list
- **sdk**: Cover API-key headers and 401 handling
- **server**: Cover API-key auth over REST and WebSocket

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
