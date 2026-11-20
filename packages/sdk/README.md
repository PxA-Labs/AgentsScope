# AgentScope Python SDK

A lightweight tracing library that instruments AI agent pipelines and streams execution traces to the AgentScope server in real time.

## Installation

The SDK will be published on PyPI as `agentscope-trace` (release pipeline [#298](https://github.com/PxA-Labs/AgentsScope/pull/298); first release pending). Until then, install it from a clone of the repository:

```bash
# Core SDK (decorators, OpenAI/Anthropic/Gemini patching, CLI)
pip install -e packages/sdk

# With optional extras
pip install -e "packages/sdk[langchain]"   # LangChain callback handler
pip install -e "packages/sdk[crewai]"      # CrewAI integration
pip install -e "packages/sdk[autogen]"     # AutoGen integration
pip install -e "packages/sdk[llamaindex]"  # LlamaIndex integration
pip install -e "packages/sdk[anthropic]"   # Anthropic SDK (for patch_anthropic)
pip install -e "packages/sdk[gemini]"      # Google Gen AI SDK (for patch_gemini)
pip install -e "packages/sdk[tiktoken]"    # exact token counts when a provider omits usage
```

> `pip install agentscope` and `pip install agentscope-sdk` install **unrelated** PyPI projects. Don't use them.

The import package is `agentscope_trace`; the `agentscope` command-line tool keeps its name.

### Migrating from `import agentscope`

Until [#297](https://github.com/PxA-Labs/AgentsScope/issues/297) the import package was called `agentscope`. Replace it with `agentscope_trace`, i.e. `s/from agentscope/from agentscope_trace/` and `s/import agentscope/import agentscope_trace/`, plus attribute uses such as `agentscope.decorators.configure(...)`:

```bash
perl -pi -e 's/\b(from|import) agentscope\b/$1 agentscope_trace/g; 1 while s/^(\s*import\s[^#]*,\s*)agentscope\b/$1agentscope_trace/; s/(?<![\w.\/@-])agentscope(?=\.\w)/agentscope_trace/g' your_module.py
```

It rewrites `from agentscope...` / `import agentscope...` lines (including `import agentscope as x` and `import os, agentscope`), and `agentscope.<name>` attribute uses and strings such as `monkeypatch.setattr("agentscope.client....")` targets. Review the diff afterwards (`git diff`, then `grep -rnw agentscope --include='*.py' .`):

- It also rewrites `agentscope.<name>` text that isn't this SDK, e.g. a bare `agentscope.example.com` host (URLs with `//` and e-mail addresses are skipped), and imports of agentscope-ai's unrelated `agentscope` package if your code also refers to that.
- Logging configuration needs updating by hand: loggers are now named `agentscope_trace.*` (for example `agentscope_trace.integrations.crewai`).
- Bare uses of the module object itself, such as `getattr(agentscope, ...)` or `print(agentscope)`, are not rewritten and become a `NameError` once the import line says `agentscope_trace`; the `grep` above lists them so you can fix them by hand.

The smallest possible change is `import agentscope_trace as agentscope`, which keeps every `agentscope.<name>` use working; `from agentscope... import` lines still need the new name.

Old imports still work for now: a deprecated `agentscope` shim aliases `agentscope_trace` and emits one `DeprecationWarning`. Both names give the same module objects, so the global client, patches and monkeypatches are shared and the two can be mixed while you migrate. Import `agentscope` (or `agentscope_trace`) once at startup, before starting threads: while that first import is still running, another thread's first import of an `agentscope.<name>` submodule can fail with ModuleNotFoundError.

The shim will be removed after at least one minor release (0.3.0 at the earliest). It is also the one file that still clashes with the unrelated `agentscope` package on PyPI, so the two can't be installed together until it's gone.

If you work on this repository with an editable install made before the rename, re-run `make setup-sdk` (or `pip install -e packages/sdk`): the old install only maps `agentscope`, so both import names fail until you do.

## Features

- **Non-blocking telemetry**: events go onto an in-memory queue and are sent in batches by a background thread, so agent execution never waits on the network.
- **Resilient transport**: WebSocket connection with automatic reconnection. Up to 5,000 events are buffered while the server is unreachable (set `max_queue_size` on `AgentScopeClient` to change it), and the oldest are dropped first.
- **Graceful shutdown**: buffered events are delivered when the process exits, even if `stop()` is never called, bounded by the client's `shutdown_timeout` (an `AgentScopeClient` argument, 5 s by default). If the server rejects the API key, the client gives up at once instead of waiting.
- **Authentication and TLS**: pass `api_key=` (or set `AGENTSCOPE_API_KEY`) and `base_url="https://..."` / `secure=True` to reach a protected remote server. See [docs/AUTHENTICATION.md](../../docs/AUTHENTICATION.md).
- **LangChain callback handler**: trace chains, tools, agents, retrievers and LLMs with two lines of code.
- **Model SDK auto-instrumentation**: `patch_openai()`, `patch_anthropic()`, `patch_gemini()`, or `patch_all()` for every installed SDK (sync, async and streaming). See [docs/PROVIDERS.md](../../docs/PROVIDERS.md).
- **Framework integrations**: CrewAI, AutoGen and LlamaIndex via the `crewai`, `autogen` and `llamaindex` extras. See [docs/INTEGRATIONS.md](../../docs/INTEGRATIONS.md).
- **Decorators**: `@trace`, `@trace_llm`, `@trace_tool`, `@trace_retriever` for any Python code.
- **Cost tracking and budgets**: per-call USD cost from the bundled pricing table, plus an optional hard budget limit.
- **CLI**: `agentscope start` launches the server and dashboard from a repository checkout.

## Usage

### LangChain

```python
from agentscope_trace import AgentScopeCallback

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
from agentscope_trace import patch_openai, unpatch_openai
from agentscope_trace.decorators import configure

configure(session_name="openai_direct")  # optional; defaults to localhost:8765
patch_openai()                            # returns False if `openai` isn't installed

client = OpenAI()
client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}])

unpatch_openai()                          # restore the original methods
```

### Decorators

```python
from agentscope_trace import trace, trace_llm, trace_tool, trace_retriever
from agentscope_trace.decorators import configure

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

When `budget_limit_usd` is set on `AgentScopeCallback`, the callback tracks cumulative LLM cost for the session. Once the limit is exceeded it marks the session `failed` and stops the run by raising `agentscope_trace.BudgetExceededError` (a subclass of `AgentScopeError`):

- The call that crosses the limit is allowed to finish, since its cost is only known when it ends.
- In async runs the error is raised as soon as that call ends, so its output is not returned.
- In sync runs the error is raised before the next model call is sent. If the crossing call was the last model call, there is nothing left to stop: the run returns normally, and the session stays `failed`.
- A model call still in flight when the limit trips (for example a parallel branch) is aborted at its next token or at its end.

Fixed in [#317](https://github.com/PxA-Labs/AgentsScope/pull/317); before it, LangChain caught the exception and the run continued ([#316](https://github.com/PxA-Labs/AgentsScope/issues/316)).

### Token counting

Token counts come from the provider's usage data when it's available. Otherwise the SDK estimates them with `tiktoken` if the `tiktoken` extra is installed, falling back to a ~4-characters-per-token heuristic.

## Development

```bash
pip install -e "packages/sdk[dev,langchain]"
pytest packages/sdk/tests
```

See the repository [CONTRIBUTING.md](../../CONTRIBUTING.md) and run `make pre-pr` before opening a pull request.
