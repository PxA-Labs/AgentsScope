<div align="center">
  <h1>AgentScope</h1>
  <p><em>Lightweight observability for multi-agent AI pipelines</em></p>

  <!-- Badges -->
  <a href="https://opensource.org/licenses/Apache-2.0">
    <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License">
  </a>
  <a href="https://www.python.org/downloads/">
    <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python Version">
  </a>
  <a href="https://nodejs.org/">
    <img src="https://img.shields.io/badge/node-20+-green.svg" alt="Node Version">
  </a>
  <a href="https://securityscorecards.dev/viewer/?uri=github.com/PxA-Labs/AgentsScope">
    <img src="https://api.securityscorecards.dev/projects/github.com/PxA-Labs/AgentsScope/badge" alt="OpenSSF Scorecard">
  </a>
  <a href="SECURITY.md">
    <img src="https://img.shields.io/badge/Security-OpenSSF%20Standard-brightgreen.svg" alt="Security Policy">
  </a>
  <a href="https://github.com/PxA-Labs/AgentsScope/pulls">
    <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">
  </a>
  <a href="https://github.com/PxA-Labs/AgentsScope/stargazers">
    <img src="https://img.shields.io/github/stars/PxA-Labs/AgentsScope?style=social" alt="GitHub Stars">
  </a>

  <p>Add two lines of Python and see everything your AI agents are doing.</p>
</div>

<br />

## The Core Value Prop

**AgentScope** is a lightweight, open-source, self-hosted observability dashboard designed specifically for multi-agent AI pipelines. 

Running complex agent setups often feels like running completely blind—you add `verbose=True`, comb through endless walls of text in the console, and guess where an error occurred. With AgentScope, you **add 2 lines of Python, and instantly see everything your agents do** on a clean, local dashboard.

Keep track of real-time events, visualize your agent DAG, monitor token usage, and browse past session history—all without relying on an external cloud provider.

**Self-hosted. No accounts. No cloud dependency.**

## Quick Demo

**BEFORE**: Running agents blindly, adding `verbose=True`, reading walls of text.

**AFTER**: Two lines of code, a beautiful dashboard showing exactly what happened.

```python
from agentscope_trace import AgentScopeCallback

cb = AgentScopeCallback(session_name="my_pipeline")
agent.run(input, callbacks=[cb])

# That's it. Open http://localhost:3000
```

## Features

- **Real-time Event Feed** — Watch your agents work in real-time
- **Live Agent DAG Graph** — Visualize the full call hierarchy, streamed as it grows
- **Token & Cost Tracking** — Token usage and estimated USD cost per call and per session
- **Cost Budgets** — Optional `budget_limit_usd` marks the session failed and stops further model calls once a spend limit is exceeded ([details](packages/sdk/README.md#budgets))
- **Event Inspector** — Click any event to see full prompt + completion text, with prompt diffs
- **Stats Dashboard** — Token breakdown, latency heatmap, error log
- **Session History & Diffing** — Browse past runs and compare two sessions side by side
- **Export / Import** — Download a session as JSON (re-importable into another instance) or as CSV for spreadsheets
- **Session Memories** — Attach tagged memories to sessions via [Mem0](https://mem0.ai) (requires `MEM0_API_KEY`)
- **One-Command Setup** — `docker compose up` and you're running
- **Integrations** — LangChain, CrewAI, AutoGen and LlamaIndex ([docs/INTEGRATIONS.md](docs/INTEGRATIONS.md)); OpenAI, Anthropic and Gemini SDK auto-instrumentation ([docs/PROVIDERS.md](docs/PROVIDERS.md)); and `@trace` decorators for any code
- **Optional API-key auth** — Protect the REST API and WebSocket with one or more keys ([docs/AUTHENTICATION.md](docs/AUTHENTICATION.md))
- **SQLite or PostgreSQL** — Zero-config SQLite by default, PostgreSQL for shared setups
- **Retention Policies** — Automatic pruning by age or session count
- **Self-Hosted** — Your data stays on your machine
- **Zero Impact** — SDK never blocks your agent pipeline

## Getting Started (5 minutes)

### Option 1: Docker (Recommended)

The easiest way to run the backend and UI:

```bash
git clone https://github.com/PxA-Labs/AgentsScope.git
cd AgentsScope
docker compose up
```

- Dashboard UI: http://localhost:3000
- Backend API/WS: http://localhost:8765

### Option 2: Manual Setup

If you prefer to run it manually:

```bash
# Server
cd packages/server
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8765

# UI (new terminal)
cd packages/ui
npm install
npm run dev

# SDK (in your project's virtualenv, from the cloned repo)
pip install -e "packages/sdk[langchain]"
```

> **Note:** The SDK is not published to PyPI yet, so install it from source as shown above.
> Do **not** run `pip install agentscope`: that name belongs to an unrelated project on PyPI.
> It will be published as `agentscope-trace` ([#298](https://github.com/PxA-Labs/AgentsScope/pull/298)) and is imported as `agentscope_trace`. `import agentscope` still works through a deprecated shim for now; see [Migrating from `import agentscope`](packages/sdk/README.md#migrating-from-import-agentscope).

### Storage Backends (SQLite & PostgreSQL)

AgentScope supports both **SQLite** (default zero-config) and **PostgreSQL** via `asyncpg`:

- **SQLite (Default)**: `sqlite+aiosqlite:///./agentscope.db`
- **PostgreSQL**: Set `DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/agentscope` in the server's environment (`export`, `uvicorn --env-file .env`, or `docker-compose.yml`). Standard PostgreSQL URIs (`postgresql://...`) are also automatically normalized to use `asyncpg`.

### Instrument Your Code

Now, just drop the callback into your code!

```python
from langchain_openai import ChatOpenAI
from langchain.chains import LLMChain
from agentscope_trace import AgentScopeCallback

# 1. Initialize the callback
cb = AgentScopeCallback(session_name="my_first_trace")

llm = ChatOpenAI(model="gpt-4o")
chain = LLMChain(llm=llm, prompt=prompt)

# 2. Add it to your callbacks
result = chain.invoke(
    {"question": "What is quantum computing?"},
    config={"callbacks": [cb]}
)

# Open http://localhost:3000 — your trace is there!
```

## Architecture

```mermaid
flowchart LR
    A[Python Code] -->|SDK| B((WebSocket))
    B --> C[FastAPI Server + SQLite / PostgreSQL]
    C -->|REST + WS| D[Next.js Dashboard UI]
```

## Usage Examples

### 1. Basic LLM Chain
```python
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from agentscope_trace import AgentScopeCallback

cb = AgentScopeCallback(session_name="basic_chain")
prompt = PromptTemplate.from_template("Tell me a joke about {topic}")
chain = prompt | ChatOpenAI()

chain.invoke({"topic": "developers"}, config={"callbacks": [cb]})
```

### 2. Multi-Agent Pipeline (AgentExecutor)
```python
from langchain.agents import create_react_agent, AgentExecutor
from agentscope_trace import AgentScopeCallback

cb = AgentScopeCallback(session_name="react_agent")
agent = create_react_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools)

agent_executor.invoke({"input": "Search for the weather in NY"}, config={"callbacks": [cb]})
```

### 3. Custom Function Trace
```python
from agentscope_trace.decorators import trace

@trace(name="My Custom Step")
def process_data(data):
    return f"Processed {data}"
```

## Configuration

**Server** (see [`packages/server/.env.example`](packages/server/.env.example)). The server reads real environment variables only; it does not load a `.env` file by itself, so pass one explicitly with `uvicorn main:app --env-file .env` or export the variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./agentscope.db` | SQLAlchemy URL. Use `postgresql+asyncpg://...` for PostgreSQL (`postgresql://` is normalized automatically) |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | `10` / `20` | PostgreSQL connection pool sizing |
| `AGENTSCOPE_RETENTION_DAYS` | unset (keep forever) | Delete sessions older than N days (`RETENTION_DAYS` also accepted) |
| `AGENTSCOPE_MAX_SESSIONS` | unset (no limit) | Keep only the newest N sessions (`MAX_SESSIONS` also accepted) |
| `AGENTSCOPE_PRUNE_INTERVAL_SECONDS` | `3600` | How often the retention job runs |
| `CORS_ALLOW_ORIGINS` | `http://localhost:3000` | Comma-separated list of allowed UI origins |
| `AGENTSCOPE_PRICING_FILE` | bundled `pricing.json` | Path to a custom model pricing table |
| `MEM0_API_KEY` | unset | Enables the session memories API |
| `AGENTSCOPE_API_KEY` / `AGENTSCOPE_API_KEYS` | unset (auth off) | One key, or a comma-separated list for rotation. When set, `/api` and `/ws` require it; keys must be 16+ characters and not a placeholder from the docs. See [docs/AUTHENTICATION.md](docs/AUTHENTICATION.md) |

The server's host and port are set on the `uvicorn` command line (`--host`, `--port`, default port `8765`).

**UI** (inlined at **build time** by Next.js, so set them before `npm run build` / `docker build`):

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8765` | Base URL of the server's REST API |
| `NEXT_PUBLIC_WS_URL` | `ws://127.0.0.1:8765` | Base WebSocket URL. The UI appends `/ws` itself, so don't include it |

In the SDK, the server location is passed in code, e.g. `AgentScopeCallback(host="localhost", port=8765)` or `agentscope_trace.decorators.configure(host=..., port=...)`. For a remote or TLS server use `base_url="https://..."` (or `secure=True`); the API key comes from `api_key=` or the `AGENTSCOPE_API_KEY` environment variable.

## Project Structure

```text
agentscope/
├── packages/
│   ├── sdk/          # Python SDK: LangChain/CrewAI/AutoGen/LlamaIndex integrations, OpenAI/Anthropic/Gemini patching, @trace decorators, CLI
│   ├── server/       # FastAPI backend: REST + WebSocket, SQLAlchemy models (SQLite/PostgreSQL)
│   └── ui/           # Next.js 16 dashboard
├── docs/             # PRD, design, schema, development, integration, provider and auth guides
├── examples/         # Runnable instrumentation examples
├── scripts/          # Developer tooling (pre-PR checks)
├── docker-compose.yml
├── Makefile
├── README.md
└── CONTRIBUTING.md
```

## Tech Stack

| Component | Technology |
|---|---|
| **SDK** | Python 3.11+, Pydantic v2, websockets |
| **Server** | FastAPI, SQLAlchemy (async), SQLite (aiosqlite) or PostgreSQL (asyncpg), uvicorn |
| **UI** | Next.js 16, React Flow, Recharts, Zustand, Tailwind CSS |

## Contributing

We welcome contributions! Please see our [CONTRIBUTING.md](./CONTRIBUTING.md) file for more details.

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'feat(ui): Add AmazingFeature'`) - *We use Conventional Commits!*
4. Run tests before submitting
5. Push to the Branch (`git push origin feature/AmazingFeature`)
6. Open a Pull Request

## Roadmap

The full execution order is tracked in [#280](https://github.com/PxA-Labs/AgentsScope/issues/280).

**Shipped**
- [x] LangChain integration
- [x] Real-time event feed
- [x] Agent DAG graph
- [x] Live DAG updates over WebSockets ([#156](https://github.com/PxA-Labs/AgentsScope/pull/156))
- [x] Prompt diff view ([#124](https://github.com/PxA-Labs/AgentsScope/pull/124))
- [x] Session diffing / comparative timeline ([#155](https://github.com/PxA-Labs/AgentsScope/pull/155))
- [x] Export / import sessions as JSON ([#125](https://github.com/PxA-Labs/AgentsScope/pull/125))
- [x] Cost budget enforcement and async event batching ([#125](https://github.com/PxA-Labs/AgentsScope/pull/125))
- [x] Raw OpenAI SDK auto-instrumentation ([#150](https://github.com/PxA-Labs/AgentsScope/pull/150))
- [x] `@trace_llm` / `@trace_tool` / `@trace_retriever` decorators ([#149](https://github.com/PxA-Labs/AgentsScope/pull/149))
- [x] Optional tiktoken token counting ([#148](https://github.com/PxA-Labs/AgentsScope/pull/148))
- [x] PostgreSQL storage backend ([#153](https://github.com/PxA-Labs/AgentsScope/pull/153))
- [x] Retention policies and auto-vacuum ([#152](https://github.com/PxA-Labs/AgentsScope/pull/152))
- [x] Session memories with category tags ([#151](https://github.com/PxA-Labs/AgentsScope/pull/151), [#154](https://github.com/PxA-Labs/AgentsScope/pull/154))
- [x] WebSocket reconnect backoff + connection status ([#135](https://github.com/PxA-Labs/AgentsScope/pull/135))
- [x] CrewAI integration ([#292](https://github.com/PxA-Labs/AgentsScope/pull/292))
- [x] AutoGen integration ([#293](https://github.com/PxA-Labs/AgentsScope/pull/293))
- [x] LlamaIndex integration ([#295](https://github.com/PxA-Labs/AgentsScope/pull/295))
- [x] Anthropic & Gemini SDK auto-instrumentation ([#288](https://github.com/PxA-Labs/AgentsScope/pull/288))
- [x] Export to CSV ([#286](https://github.com/PxA-Labs/AgentsScope/pull/286))
- [x] Optional API-key authentication ([#287](https://github.com/PxA-Labs/AgentsScope/pull/287))
- [x] Graceful SDK shutdown: buffered events are delivered at exit ([#296](https://github.com/PxA-Labs/AgentsScope/pull/296))
- [x] PyPI release pipeline for `agentscope-trace` ([#298](https://github.com/PxA-Labs/AgentsScope/pull/298)); first release not published yet

**Planned**
- [ ] UI component split with unit and E2E tests ([#275](https://github.com/PxA-Labs/AgentsScope/issues/275))
- [ ] Rename the import package to `agentscope_trace` ([#297](https://github.com/PxA-Labs/AgentsScope/issues/297))
- [ ] Production / cloud deployment configs ([#269](https://github.com/PxA-Labs/AgentsScope/issues/269))
- [ ] Multi-user accounts, projects and RBAC ([#277](https://github.com/PxA-Labs/AgentsScope/issues/277))

## FAQ

**Q: Is this production-ready?**  
A: AgentScope is primarily a developer tool designed for local debugging and observability during the development of your pipelines.

**Q: Does it work with CrewAI, AutoGen or LlamaIndex?**  
A: Yes. Each framework is instrumented through its own extension point: `AgentScopeCrewAIListener` on CrewAI's event bus, `AgentScopeAutoGenTracer` / `trace_model_client` for AutoGen, and `instrument_llamaindex()` for LlamaIndex's instrumentation API. Install the matching extra (`packages/sdk[crewai]`, `[autogen]`, `[llamaindex]`); see [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) for usage and known limitations. LangChain (`AgentScopeCallback`), the OpenAI, Anthropic and Gemini SDKs (`patch_all()`), and any Python function (`@trace` and friends) are covered too.

**Q: Where is my data stored?**  
A: Your data never leaves your infrastructure. By default it goes to a local SQLite file (`agentscope.db` in the server's working directory, or the `sqlite_data` volume under Docker Compose). Set `DATABASE_URL` to use PostgreSQL instead. Old sessions can be pruned automatically with `AGENTSCOPE_RETENTION_DAYS` / `AGENTSCOPE_MAX_SESSIONS`.

**Q: Does the SDK slow down my agents?**  
A: It shouldn't. Events go onto an in-memory queue and are sent in batches by a background thread, so instrumented calls never wait on the network. If the server is unreachable, events are buffered (up to 5,000 by default, set with `AgentScopeClient(max_queue_size=...)`; the oldest are dropped first). Measured overhead and latency are in [docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## License

Distributed under the Apache License 2.0. See `LICENSE` for more information.

## Acknowledgments

A huge thank you to the open-source tools that made AgentScope possible:
- [LangChain](https://github.com/langchain-ai/langchain)
- [FastAPI](https://github.com/tiangolo/fastapi)
- [React Flow](https://reactflow.dev/)
- [Next.js](https://nextjs.org/)
