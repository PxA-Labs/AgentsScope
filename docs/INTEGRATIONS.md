# Framework integrations

AgentScope instruments agent frameworks through their own extension points (callbacks, event buses, instrumentation handlers or model-client wrappers), so no monkey-patching of framework internals is needed.

| Framework | How | Install |
|---|---|---|
| LangChain | `AgentScopeCallback` passed in `callbacks=[...]` | `packages/sdk[langchain]` |
| CrewAI | `AgentScopeCrewAIListener` on CrewAI's event bus | `packages/sdk[crewai]` |
| AutoGen | `AgentScopeAutoGenTracer` / `trace_model_client` ([AUTOGEN.md](AUTOGEN.md)) | `packages/sdk[autogen]` |
| LlamaIndex | `instrument_llamaindex()` on the instrumentation API ([LLAMAINDEX.md](LLAMAINDEX.md)) | `packages/sdk[llamaindex]` |

Model SDKs used directly (OpenAI, Anthropic, Gemini) are covered by `patch_all()`; see [PROVIDERS.md](PROVIDERS.md).

## CrewAI

```python
from agentscope_trace.integrations.crewai import AgentScopeCrewAIListener

listener = AgentScopeCrewAIListener(
    host="127.0.0.1", port=8765,       # AgentScope server
    session_name="research-crew",      # optional
    session_metadata={"env": "dev"},   # optional
)
crew.kickoff(inputs={...})
listener.close()                        # delivers pending events, stops the client
```

Create the listener **once per process**, before `kickoff()`. It subscribes to `crewai_event_bus`, so every crew and Flow run in the process is recorded in that session. `instrument_crewai(**kwargs)` is an alias that returns the listener.

CrewAI **Flows** work the same way: create the listener, then call `flow.kickoff()`. The flow is a node and the crews it runs sit under it.

### What you see in the dashboard

The DAG reads **crew → task → agent → tool / LLM**, under a **flow** node when a Flow runs the crews:

| CrewAI event | AgentScope event | Node name |
|---|---|---|
| flow started / finished / failed | `chain_start` / `chain_end` / `chain_error` (`agent_type="flow"`) | flow name (its class name by default) |
| crew kickoff started / completed / failed | `chain_start` / `chain_end` / `chain_error` (`agent_type="crew"`) | crew `name` |
| task started / completed / failed | `chain_*` (`agent_type="task"`) | task name, or its description |
| agent execution started / completed / error | `chain_*` (`agent_type="agent"`) | agent role |
| standalone `Agent.kickoff()` (lite agent) started / completed / error | `chain_*` (`agent_type="agent"`) | agent role |
| tool usage started / finished / error | `tool_start` / `tool_end` / `tool_error` | tool name |
| LLM call started / completed / failed | `llm_start` / `llm_end` / `llm_error` | model |

- **Tokens and cost**: LLM events carry the usage CrewAI reports (`prompt_tokens`/`completion_tokens` or `input_tokens`/`output_tokens`). Cost uses the shared pricing table, so models not in `pricing.json` cost `0.0`.
- **Session status**: when a top-level Flow or crew completes or fails, the session is marked `completed` / `failed`, once. Crews run by a Flow don't change it, so a two-crew Flow is marked once when the flow ends, and stays `running` between its crews. A crew or Flow kicked off from inside another crew's tool or agent, or from inside another Flow, doesn't change it either. Pass `mark_session_status=False` to manage it yourself.
- **Flows**: flow methods aren't shown, so each crew is attached to its flow. A flow paused for human feedback (`flow_paused`) stays `running` and doesn't change the session status.
- **Parents**: CrewAI emits internal events (for example, each agent's executor runs as a Flow). These aren't shown as nodes. CrewAI marks its internal flows with `suppress_flow_events`, which is how the listener tells them apart from yours. Each node is attached to its nearest shown ancestor.
- **Ordering**: handlers are registered as async, so CrewAI's bus runs them in emission order. Its sync handlers run in a thread pool, where a child could otherwise be processed before its parent.
- Long text (prompts, outputs, tool I/O) is truncated to 4,000 characters per field.
- **Memory**: the listener remembers only CrewAI scopes that are still open, so its memory stays flat in long-running processes however many kickoffs it sees.

### Limitations

- **Budgets**: `budget_limit_usd` (available on the LangChain callback) isn't supported. CrewAI event handlers can't abort a running crew.
- Requires `crewai>=1.15.41`. The listener relies on `started_event_id` / `parent_event_id`, which older releases may not provide.
- Flow method, memory, knowledge and reasoning events are tracked only for parentage, not shown.
- **No nesting under `@trace`**: the listener reports through its own client and session, not the global client used by `@trace`, so a crew started inside a `@trace` function is a top-level node in the listener's session.
