# AgentScope Python SDK

A lightweight tracing library that instruments AI agent pipelines and streams execution traces to the AgentScope server in real time.

## Installation

The SDK is not on PyPI yet (tracked in [#274](https://github.com/PxA-Labs/AgentsScope/issues/274)). Install it from a clone of the repository:

```bash
# Core SDK (decorators, OpenAI patching, CLI)
pip install -e packages/sdk

# With optional extras
pip install -e "packages/sdk[langchain]"   # LangChain callback handler
pip install -e "packages/sdk[tiktoken]"    # exact token counts when a provider omits usage
```

> `pip install agentscope` installs an **unrelated** PyPI project. Don't use it.

## Features

- **Non-blocking telemetry**: events go onto an in-memory queue and are sent in batches by a background thread, so agent execution never waits on the network.
- **Resilient transport**: WebSocket connection with automatic reconnection. Up to 5,000 events are buffered while the server is unreachable, and the oldest are dropped first.
- **LangChain callback handler**: trace chains, tools, agents, retrievers and LLMs with two lines of code.
- **OpenAI SDK auto-instrumentation**: `patch_openai()` traces `chat.completions.create` (sync, async and streaming).
- **Decorators**: `@trace`, `@trace_llm`, `@trace_tool`, `@trace_retriever` for any Python code.
- **Cost tracking and budgets**: per-call USD cost from the bundled pricing table, plus an optional hard budget limit.
- **CLI**: `agentscope start` launches the server and dashboard from a repository checkout.

## Usage

### LangChain

```python
from agentscope import AgentScopeCallback

cb = AgentScopeCallback(
    session_name="my_pipeline",       # optional, defaults to a timestamp
    session_metadata={"env": "dev"},  # optional tags
    host="localhost", port=8765,      # where the AgentScope server runs
    budget_limit_usd=1.00,            # optional; see "Budgets" below
)
chain.invoke({"question": "..."}, config={"callbacks": [cb]})
```

### Raw OpenAI SDK

```python
from openai import OpenAI
from agentscope import patch_openai, unpatch_openai
from agentscope.decorators import configure

configure(session_name="openai_direct")  # optional; defaults to localhost:8765
patch_openai()                            # returns False if `openai` isn't installed

client = OpenAI()
client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}])

unpatch_openai()                          # restore the original methods
```

### Decorators

```python
from agentscope import trace, trace_llm, trace_tool, trace_retriever
from agentscope.decorators import configure

configure(host="127.0.0.1", port=8765, session_name="custom_pipeline")

@trace(name="plan_step", agent_type="agent")  # generic chain_* events; works on sync and async functions
def plan(task: str) -> str: ...

@trace_llm(model="my-local-model")            # llm_* events; the prompt is read from `prompt`/`messages`/`input`/...
def call_model(prompt: str) -> str: ...

@trace_tool(name="calculator")                # tool_* events
def calculate(expression: str) -> str: ...

@trace_retriever(name="vector_store")         # retriever_* events with the returned documents
def search(query: str) -> list[str]: ...
```

Nested decorated calls are linked automatically, so they appear as parent and child nodes in the DAG.

### Budgets

When `budget_limit_usd` is set on `AgentScopeCallback`, the callback tracks cumulative LLM cost for the session. Once the limit is exceeded it marks the session `failed` and raises `agentscope.BudgetExceededError` (a subclass of `AgentScopeError`) out of the run. The call that crosses the limit completes, since its cost is only known when it ends; the run then stops before the next model call (sync or async). This requires the fix in [#317](https://github.com/PxA-Labs/AgentsScope/pull/317): before it, LangChain caught the exception and the run continued ([#316](https://github.com/PxA-Labs/AgentsScope/issues/316)).

### Token counting

Token counts come from the provider's usage data when it's available. Otherwise the SDK estimates them with `tiktoken` if the `tiktoken` extra is installed, falling back to a ~4-characters-per-token heuristic.

## Development

```bash
pip install -e "packages/sdk[dev,langchain]"
pytest packages/sdk/tests
```

See the repository [CONTRIBUTING.md](../../CONTRIBUTING.md) and run `make pre-pr` before opening a pull request.
