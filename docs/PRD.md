# Product Requirements Document (PRD) - AgentScope

> **Status (last updated 2026-11-15):** All 10 MVP features (§7) have shipped, along with most of the original Post-MVP list (§8.1).
> Sections 1–7, 9 and 12 describe the original MVP requirements and are kept as written for reference. §5 notes where the
> implementation has since moved on. Open work is tracked in [#280](https://github.com/PxA-Labs/AgentsScope/issues/280).

## 1. Executive Summary

**AgentScope** is a lightweight, open-source, self-hosted observability dashboard for multi-agent AI pipelines. 

Debugging multi-agent AI pipelines is notoriously difficult. Developers currently lack visibility into which agent called which tool, the exact prompt and completion text, total token costs, and the overall call hierarchy of complex executions. AgentScope solves this by providing a lightweight, local observability dashboard. With just two lines of Python code, developers can instrument their LangChain applications and immediately visualize real-time event feeds, agent execution graphs, and token usage metrics—all self-hosted with no accounts or cloud dependencies required.

**Target Audience:** AI/ML developers building and debugging multi-agent pipelines.

## 2. Goals & Objectives

### Primary Goals
- Give developers instant visibility into multi-agent pipeline execution.
- Provide clear, real-time insights into prompts, completions, and tool executions.
- Visualize agent call hierarchies to understand complex chains.

### Secondary Goals
- Persist session history for retrospective debugging and analysis.
- Provide token usage and cost estimations per session.

### Non-Goals
- Cloud deployment or SaaS offering.
- Team-based features or collaboration tools.
- User authentication or authorization.
- Production monitoring at high scale (focused on dev/staging).

## 3. User Personas

- **Solo AI Developer:** Building rapid prototypes with LangChain, needs fast iteration and instant feedback on why an agent failed or hallucinates.
- **ML Engineer:** Debugging complex, multi-layered multi-agent chains in dev/staging environments, requiring deep dives into intermediate steps and token consumption.
- **Open Source Contributor:** Looking to extend observability integrations beyond LangChain (e.g., CrewAI, AutoGen) and contribute to the dashboard ecosystem.

## 4. User Stories

| ID | As a... | I want to... | So that I can... |
|---|---|---|---|
| 1 | Developer | Add 2 lines of code to my LangChain setup to see events in a dashboard | Instrument my pipeline with minimal friction |
| 2 | Developer | See the exact prompt and completion text for each LLM call | Debug unexpected outputs or hallucinations |
| 3 | Developer | View token usage and estimated cost per session | Optimize my pipeline's resource consumption |
| 4 | Developer | See a DAG visualization of my agent call hierarchy | Understand complex multi-agent interactions |
| 5 | Developer | Filter events by agent name and event type | Quickly find relevant information in large sessions |
| 6 | Developer | Have sessions persist in a local database | Debug past runs without having to re-execute them |
| 7 | Developer | Watch real-time event streaming as my pipeline runs | Monitor execution progress and identify hangs |
| 8 | Developer | Click on any event and see its full payload | Inspect raw data, tool inputs, and intermediate states |
| 9 | Developer | Run everything locally with one command (docker-compose) | Setup the environment quickly without manual configuration |
| 10 | Developer | See error events clearly highlighted in the dashboard | Find and fix pipeline failures fast |

## 5. Functional Requirements

### 5.1 Python SDK (`packages/sdk/`)
- **Integration:** Hook into LangChain via custom `BaseCallbackHandler`.
- **Callbacks Implemented:**
  - `on_llm_start`, `on_llm_end`, `on_llm_error`
  - `on_chain_start`, `on_chain_end`, `on_chain_error`
  - `on_tool_start`, `on_tool_end`, `on_tool_error`
  - `on_agent_action`, `on_agent_finish`
- **Communication:** Establish a WebSocket connection to the Server to stream events asynchronously.
- **Resilience:** Buffer events in-memory if the WebSocket connection drops, and attempt reconnection with exponential backoff.

### 5.2 Server (`packages/server/`)
- **Framework:** FastAPI application.
- **Database:** SQLite for persistent storage of sessions and events. *(Now SQLite by default, with optional PostgreSQL; see §10.)*
- **Endpoints:**
  - `GET /api/sessions`: List all historical sessions.
  - `GET /api/sessions/{id}`: Retrieve full details and events for a specific session.
  - `DELETE /api/sessions/{id}`: Delete a session.
  - `GET /api/stats`: Retrieve aggregate statistics (total tokens, total runs, etc.). *(Not implemented as a global endpoint; per-session stats are served by `GET /api/sessions/{id}/stats`.)*
- **WebSocket Route:**
  - `WS /ws/events`: Receive events from the Python SDK, persist them to SQLite, and immediately broadcast them to connected UI clients. *(Implemented as a single `WS /ws` route; clients identify themselves with `?client_type=sdk|ui`.)*

### 5.3 UI Dashboard (`packages/ui/`)
- **Framework:** Next.js 14 (App Router) + React. *(Now on Next.js 16.)*
- **Components:**
  - **Session List Sidebar:** Displays past and current sessions, sortable by date.
  - **Real-time Event Feed:** A scrolling list of events, auto-updating via WebSocket. Highlights errors in red.
  - **Event Inspector (Drawer/Modal):** Displays the full JSON payload of a selected event (prompts, responses, tool inputs).
  - **Agent DAG Graph:** Uses React Flow to visualize the execution hierarchy (chains -> agents -> tools -> LLMs).
  - **Metrics Header:** Displays session duration, token count, and estimated cost.
  - **Filters:** Dropdowns to filter the event feed by Event Type or Agent Name.

## 6. Non-Functional Requirements

- **Performance:** The Python SDK must never block the main agent pipeline execution (fire-and-forget asynchronous networking).
- **Latency:** Events emitted by the SDK should appear in the UI dashboard within 100ms.
- **Storage:** Use SQLite configured in WAL (Write-Ahead Logging) mode to support concurrent reads (UI) and writes (Server receiving events).
- **Reliability:** The SDK must buffer events if the server is temporarily unreachable, preventing data loss during local network hiccups.
- **Security:** Local-only deployment. The server binds to `localhost` or `127.0.0.1` by default. No authentication required for the initial V1 release.

## 7. MVP Scope

The Minimum Viable Product (MVP) consists of the following 10 features:

1. **LangChain Integration:** Python SDK with `BaseCallbackHandler`.
2. **Real-time Event Feed:** WebSocket streaming to UI.
3. **Token Counter:** Tracking prompt and completion tokens.
4. **Session Persistence:** Storing execution history in SQLite.
5. **Agent DAG Graph:** Basic visualization using React Flow.
6. **Event Inspector:** Viewing raw event payloads in the UI.
7. **Session List:** Browsing historical runs.
8. **Basic Stats:** Aggregate metrics dashboard.
9. **Docker Compose:** One-click local deployment.
10. **CLI Launcher:** Alternative `agentscope start` command to spin up services.

## 8. Post-MVP / Out of Scope

The following features were explicitly deferred past the MVP. Their current status:

### 8.1 Shipped after the MVP
| Feature | Delivered in |
|---|---|
| Live, dynamic DAG updates over WebSockets | [#156](https://github.com/PxA-Labs/AgentsScope/pull/156) |
| PostgreSQL storage backend | [#153](https://github.com/PxA-Labs/AgentsScope/pull/153) |
| Cost budget enforcement (`budget_limit_usd`) | [#125](https://github.com/PxA-Labs/AgentsScope/pull/125) |
| Prompt diff view across iterations | [#124](https://github.com/PxA-Labs/AgentsScope/pull/124) |
| Export / import of session data as JSON | [#125](https://github.com/PxA-Labs/AgentsScope/pull/125) |
| Session diffing / comparative timeline *(not in original list)* | [#155](https://github.com/PxA-Labs/AgentsScope/pull/155) |
| Retention policies and auto-vacuum *(not in original list)* | [#152](https://github.com/PxA-Labs/AgentsScope/pull/152) |
| Raw OpenAI SDK instrumentation and specialized trace decorators *(not in original list)* | [#150](https://github.com/PxA-Labs/AgentsScope/pull/150), [#149](https://github.com/PxA-Labs/AgentsScope/pull/149) |

### 8.2 Still planned
| Feature | Tracking issue |
|---|---|
| CrewAI integration | [#264](https://github.com/PxA-Labs/AgentsScope/issues/264) |
| AutoGen integration | [#265](https://github.com/PxA-Labs/AgentsScope/issues/265) |
| LlamaIndex integration | [#266](https://github.com/PxA-Labs/AgentsScope/issues/266) |
| Export session data to CSV | [#267](https://github.com/PxA-Labs/AgentsScope/issues/267) |
| Authentication (API keys) | [#268](https://github.com/PxA-Labs/AgentsScope/issues/268) |
| RBAC and team collaboration | [#277](https://github.com/PxA-Labs/AgentsScope/issues/277) |
| Cloud deployment configurations | [#269](https://github.com/PxA-Labs/AgentsScope/issues/269) |
| Rate-limiting / budget *alerts* (beyond hard budget limits) | not yet scheduled |

## 9. Success Metrics

- **Ease of Use:** Instrumentation requires exactly 2 lines of code (`from agentscope_trace import AgentScopeCallback; callbacks=[AgentScopeCallback()]`).
- **Responsiveness:** < 1 second latency from event emission to UI rendering under normal load.
- **Time to Value:** < 5 minutes from `git clone` to viewing the first event in the running dashboard.
- **Performance Impact:** Zero measurable impact (blocking) on the primary agent pipeline execution time.

## 10. Technical Constraints

- **Language:** Python 3.11+ required for the SDK and Server.
- **Frontend UI:** Next.js 16 utilizing the App Router and strict TypeScript configuration.
- **Database:** SQLite (WAL mode) is the default, zero-configuration storage engine. PostgreSQL (via `asyncpg`) is supported for shared or larger deployments through `DATABASE_URL`.
- **Transport:** WebSocket protocol for all real-time communication.
- **Dependencies:** Minimal third-party dependencies to ensure easy installation and reduced conflict surface.

## 11. Risks & Mitigations

| Risk | Impact | Mitigation Strategy |
|---|---|---|
| **LangChain API changes** | SDK callbacks break | Pin the integration to `langchain-core` and utilize the most stable callback interfaces. |
| **WebSocket reliability** | Dropped events | Implement an in-memory buffer and robust reconnection logic with exponential backoff in the SDK. |
| **Large sessions overwhelming SQLite** | UI/Server sluggishness | Implement pagination for event retrieval and a `MAX_SESSIONS` pruning mechanism to delete old data. |

## 12. Suggested Timeline

- **Week 1-2:** Develop Python SDK (LangChain callbacks) + FastAPI Server core (SQLite setup, WebSocket ingestion).
- **Week 3-4:** Build Next.js 14 UI dashboard (Event Feed, React Flow DAG, Event Inspector).
- **Week 5:** Integration testing, robust error handling, example projects, and Docker Compose setup.
- **Week 6:** Finalize documentation (README, setup guides), overall polish, and V1 release.
