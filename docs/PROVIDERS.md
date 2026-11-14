# Provider SDK auto-instrumentation

Besides the LangChain callback and the `@trace` decorators, the SDK can patch official LLM provider SDKs so that **every** call made through them is traced. No code changes are needed at the call sites.

| Function | SDK | Calls traced | Install |
|---|---|---|---|
| `patch_openai()` | `openai` | `chat.completions.create` (sync, async, `stream=True`) | `openai` |
| `patch_anthropic()` | `anthropic` | `messages.create` (sync, async, `stream=True`) and the `messages.stream(...)` helper | `packages/sdk[anthropic]` |
| `patch_gemini()` | `google-genai` (Python 3.11+) | `models.generate_content`, `models.generate_content_stream`, and their `client.aio` versions | `packages/sdk[gemini]` |
| `patch_all()` | all of the above | patches whichever SDKs are installed | |

Each patch function has a matching `unpatch_*()`. All patching is at the class level, so it affects every client instance in the process.

```python
from agentscope import patch_all, trace
from agentscope.decorators import configure

configure(session_name="my-agent")   # optional: server host/port, api_key
patch_all()                          # {"openai": True, "anthropic": True, "gemini": False}

@trace(name="planner", agent_type="agent")
def plan():
    ...  # provider calls made here show up as children of "planner" in the DAG
```

## What gets recorded

Each call produces an `llm_start` event and an `llm_end` (or `llm_error`) event with the same `event_id`:

- `agent_name`: `"<Provider>:<model>"`, e.g. `Anthropic:claude-3-5-sonnet-20241022`
- `payload.prompts`: system prompt and messages rendered as `role: text`. Non-text blocks are summarised (`[image]`, `[tool_result …]`).
- `payload.completion`: response text. Tool and function calls are rendered as `[tool_use name: {...}]` / `[function_call name: {...}]`. Model reasoning ("thinking" / thought parts) is excluded.
- `payload.prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`: from the provider's usage data and the shared pricing table. Models not in `pricing.json` get `cost_usd = 0.0`.
- `payload.usage_details`: provider-specific counters, when present:
  - Anthropic: `cache_read_input_tokens`, `cache_creation_input_tokens`. These are billed at different rates and are **not** included in `prompt_tokens` or the cost estimate.
  - Gemini: `thoughts_token_count`, `cached_content_token_count`, `tool_use_prompt_token_count`

## Streaming

- Streams are passed through untouched. `llm_end` is emitted when the stream is exhausted, closed, or abandoned early (with whatever was received). An exception during iteration emits `llm_error`.
- Anthropic `messages.stream(...)` is recorded when its `with` block exits, using the SDK's final message snapshot.

## Behaviour on failure

- If the SDK isn't installed, the patch function logs a warning and returns `False`. `patch_all()` skips it without logging.
- If the installed SDK has an unexpected layout, the patch function raises `AgentScopeError`. `patch_all()` logs it and reports `False`.
- Tracing never changes the SDK's return values or exceptions, and telemetry errors are swallowed.
