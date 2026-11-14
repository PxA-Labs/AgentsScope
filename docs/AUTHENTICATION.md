# Authentication

AgentScope is local-first. **By default there is no authentication**, and everything works with zero configuration on `localhost`.

When the server is reachable by others (a shared dev box, a team server, a cloud VM), enable **API-key authentication**. It's a single-tenant scheme: anyone with a valid key has full access. Per-user accounts and roles are tracked in [#277](https://github.com/PxA-Labs/AgentsScope/issues/277).

## Enabling it on the server

```bash
# Generate a key
python -c "import secrets; print(secrets.token_urlsafe(32))"

# One key
export AGENTSCOPE_API_KEY=<key>

# Or several, comma-separated (e.g. while rotating keys)
export AGENTSCOPE_API_KEYS=<old-key>,<new-key>
```

Both variables can be set at once; every key listed in either is accepted. With Docker Compose, add `AGENTSCOPE_API_KEY` under the `server` service's `environment:`.

| Route | Without a key configured | With a key configured |
|---|---|---|
| `GET /health`, `/docs`, `/openapi.json` | public | public |
| `/api/*` (all methods) | open | requires `Authorization: Bearer <key>`, otherwise **401** |
| `WS /ws` | open | requires the key (see below), otherwise closed with code **4401** |

Keys are compared in constant time. Rejected requests are logged with method, path and client address, never with the supplied key.

## Python SDK

Pass the key explicitly, or set the same `AGENTSCOPE_API_KEY` environment variable in the process running your agents:

```python
from agentscope import AgentScopeCallback
from agentscope.decorators import configure

cb = AgentScopeCallback(api_key="<key>")   # LangChain
configure(api_key="<key>")                 # @trace decorators and patch_openai()
```

The SDK sends `Authorization: Bearer <key>` on REST calls and on the WebSocket handshake. If the server rejects the key, the SDK logs a single warning and keeps retrying in the background. It never raises into your code.

## Dashboard

When the server answers 401 (or closes the WebSocket with 4401), the dashboard shows a banner asking for the key. The key is saved in that browser's `localStorage` and sent:

- as `Authorization: Bearer <key>` on REST requests
- as a WebSocket subprotocol `agentscope.auth.<base64url(key)>`, offered alongside `agentscope`, because browsers can't set headers on WebSocket connections. The key is never put in the URL, so it doesn't end up in access logs.

For private deployments you can instead bake a key into the UI build with `NEXT_PUBLIC_AGENTSCOPE_API_KEY`. Like every `NEXT_PUBLIC_*` variable it's embedded in the JavaScript bundle, so **anyone who can load the dashboard can read it**. Only use it when the dashboard itself is protected (VPN, SSO proxy).

## Writing your own client

- REST: send `Authorization: Bearer <key>`.
- WebSocket: either send the same header on the handshake (server-side clients), or offer the subprotocols `agentscope` and `agentscope.auth.<key encoded as base64url without padding>`. The server echoes `agentscope`.
- Treat close code `4401` as "credentials rejected, don't retry with the same key".

## Limitations

- One shared key with full read/write access; no scopes or per-user identity.
- Use TLS (HTTPS / WSS) whenever traffic leaves the machine. Bearer keys are sent in clear text over plain HTTP.
- Keys are read from the environment at request time, but changing the environment of a running process usually requires a restart.
