# Authentication

AgentScope is local-first. **By default there is no authentication**, and everything works with zero configuration on `localhost`.

When the server is reachable by others (a shared dev box, a team server, a cloud VM), enable **API-key authentication**. It's a single-tenant scheme: anyone with a valid key has full access. Per-user accounts and roles are tracked in [#277](https://github.com/PxA-Labs/AgentsScope/issues/277).

## Enabling it on the server

```bash
# Generate a key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# One key. The whole value is the key; it is never split on commas.
export AGENTSCOPE_API_KEY=<key>

# Or several, comma-separated (e.g. while rotating keys)
export AGENTSCOPE_API_KEYS=<old-key>,<new-key>
```

Both variables can be set at once; every key listed in either is accepted. With Docker Compose, uncomment the `AGENTSCOPE_API_KEY` line under the `server` service's `environment:` and export the key in the shell that runs `docker compose`.

### Key policy

The server checks the configuration at startup:

| Situation | Result |
|---|---|
| A key shorter than **16 characters** | refuses to start |
| A key copied from the docs (`change-me`, `changeme`, `old-key`, `new-key`, `<key>`, ...) | refuses to start |
| A variable is set but empty or whitespace-only, and no other key is configured | starts with auth **disabled** and logs a warning (e.g. `${AGENTSCOPE_API_KEY}` expanded from an unset shell variable) |
| `AGENTSCOPE_API_KEY` contains a comma | starts, logs a warning pointing to `AGENTSCOPE_API_KEYS` |

Startup errors and warnings name the variable but never print the key. If a weak key gets into the environment after startup anyway, it never authenticates, and auth stays enabled (fail closed).

### What is protected

| Route | Without a key configured | With a key configured |
|---|---|---|
| `GET /health`, `/docs`, `/redoc`, `/openapi.json` | public | public |
| `/api` and everything under it (all methods, including unknown paths) | open | requires `Authorization: Bearer <key>`, otherwise **401** |
| `WS /ws` | open | requires the key (see below), otherwise closed with code **4401** |

The check runs in an ASGI middleware before routing. An unauthenticated request gets a 401 before its body is read or validated, and an unknown `/api/...` path also gets 401 rather than 404, so session IDs and routes can't be probed. CORS preflight requests don't need the key, and 401 responses carry CORS headers so the dashboard can react to them.

Keys are compared in constant time as fixed-length HMAC-SHA256 digests (keyed per process), so the length of the configured key isn't revealed either. Rejected requests are logged with method, path and client address, never with the supplied key. To keep a misconfigured client from flooding the log, there is at most one warning per client address per minute; the next one reports how many rejections were suppressed.

## Python SDK

Pass the key explicitly, or set the same `AGENTSCOPE_API_KEY` environment variable in the process running your agents. Whenever the server isn't on the same machine, connect over TLS:

```python
from agentscope import AgentScopeCallback
from agentscope.decorators import configure

# LangChain
cb = AgentScopeCallback(base_url="https://agentscope.example.com", api_key="<key>")

# @trace decorators and patch_openai()
configure(base_url="https://agentscope.example.com", api_key="<key>")

# Equivalent, keeping host/port
configure(host="agentscope.example.com", port=443, secure=True, api_key="<key>")
```

- `base_url` accepts `http://`, `https://`, `ws://` or `wss://`, with an optional port and path prefix (for a reverse proxy, e.g. `https://example.com/agentscope`). The scheme decides: `https`/`wss` means REST over HTTPS and the WebSocket over WSS. It overrides `host`, `port` and `secure`.
- `secure=True` switches `host:port` from `http`/`ws` to `https`/`wss`.
- The defaults are unchanged (`http://localhost:8765`). If an API key is set and the SDK would send it over plain `http`/`ws` to a host other than localhost, it logs a warning once.
- Invalid URLs, URLs containing credentials or a query string, and `secure=True` combined with a plain `http://` base URL raise `ValueError` when the client is created.

The SDK sends `Authorization: Bearer <key>` on REST calls and on the WebSocket handshake. If the server rejects the key, the SDK logs a single warning and keeps retrying in the background, waiting the maximum backoff (30 s) between attempts. It never raises into your code.

## Dashboard

When the server answers 401 (or closes the WebSocket with 4401), the dashboard shows a banner asking for the key and stops polling and reconnecting until one is saved. The key is saved in that browser's `localStorage` and sent:

- as `Authorization: Bearer <key>` on REST requests
- as a WebSocket subprotocol `agentscope.auth.<base64url(key)>`, offered alongside `agentscope`, because browsers can't set headers on WebSocket connections. The key is never put in the URL, so it doesn't end up in access logs.

For private deployments you can instead bake a key into the UI build with `NEXT_PUBLIC_AGENTSCOPE_API_KEY`. Like every `NEXT_PUBLIC_*` variable it's embedded in the JavaScript bundle, so **anyone who can load the dashboard can read it**. Only use it when the dashboard itself is protected (VPN, SSO proxy).

## Writing your own client

- REST: send `Authorization: Bearer <key>`.
- WebSocket: either send the same header on the handshake (server-side clients), or offer the subprotocols `agentscope` and `agentscope.auth.<key encoded as base64url without padding>`. The server echoes `agentscope`.
- Treat close code `4401` as "credentials rejected, don't retry with the same key".

## Limitations

- One shared key with full read/write access; no scopes or per-user identity.
- Use TLS (HTTPS / WSS) whenever traffic leaves the machine: terminate TLS at a reverse proxy in front of the server and point the SDK at it with `base_url="https://..."`. Bearer keys are sent in clear text over plain HTTP.
- Keys are read from the environment at request time, but changing the environment of a running process usually requires a restart.
