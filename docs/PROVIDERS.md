# Provider SDK auto-instrumentation

Besides the LangChain callback and the `@trace` decorators, the SDK can patch official LLM provider SDKs so that **every** call made through them is traced. No code changes are needed at the call sites.

| Function | SDK | Calls traced | Install |
|---|---|---|---|
| `patch_openai()` | `openai` | `chat.completions.create` (sync, async, `stream=True`) | `openai` |
| `patch_anthropic()` | `anthropic` | `messages.create` (sync, async, `stream=True`), `messages.parse`, and the `messages.stream(...)` helper | `packages/sdk[anthropic]` |
| `patch_gemini()` | `google-genai` (Python 3.11+) | `models.generate_content`, `models.generate_content_stream`, and their `client.aio` versions | `packages/sdk[gemini]` |
| `patch_all()` | all of the above | patches whichever SDKs are installed | |

Each patch function has a matching `unpatch_*()`. All patching is at the class level, so it affects every client instance in the process.

```python
from agentscope_trace import patch_all, trace
from agentscope_trace.decorators import configure

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
  - Gemini: `thoughts_token_count`, `cached_content_token_count`, `tool_use_prompt_token_count`. Thinking tokens are billed at the output rate, so `thoughts_token_count` is **also** included in `completion_tokens` and the cost estimate (Anthropic's `output_tokens` already include thinking).
- Gemini model names are normalised for pricing: `models/gemini-1.5-flash` and Vertex AI resource names such as `projects/…/publishers/google/models/gemini-1.5-flash` are recorded as `gemini-1.5-flash`.

## Streaming

- Streamed responses are returned wrapped in a thin proxy that records chunks as you iterate. The proxy forwards iteration, `close()`, context-manager use and attribute access to the SDK's stream, but it is not the SDK's class: `isinstance(stream, anthropic.Stream)` (or `openai.Stream`) is `False`.
- `llm_end` is emitted when the stream is exhausted, closed, or abandoned early (with whatever was received). An exception raised by the stream during iteration emits `llm_error`.
- Anthropic `messages.stream(...)`: the trace starts when the `with` block is entered (a manager that is never entered records nothing) and is recorded when the block exits, using the SDK's message snapshot. If your own code raises inside the block after the message completed, the call is still recorded as `llm_end` with its usage; `llm_error` is emitted only if the exception arrives before the message is complete.

## Behaviour on failure

- If the SDK isn't installed, the patch function logs a warning and returns `False`. `patch_all()` skips it without logging.
- If the installed SDK has an unexpected layout, the patch function raises `AgentScopeError`. `patch_all()` logs it and reports `False`.
- Exceptions from the SDK are re-raised unchanged, and telemetry errors are swallowed. Non-streaming return values are the SDK's own objects; streamed responses are wrapped as described above.

## Known limitations

- **Streams are proxies.** Code that checks `isinstance(..., anthropic.Stream)` / `openai.Stream` / `AsyncStream`, or relies on the exact stream type, sees the wrapper instead.
- **Raw and streaming-response wrappers record an empty `llm_end`.** Calls through `with_raw_response` / `with_streaming_response` are traced, but the SDK returns an HTTP response object rather than a parsed message, so `completion` is empty and token counts and cost are missing. This also applies to `patch_openai()`.
- **Anthropic beta endpoints aren't traced.** `client.beta.messages.*` uses separate resource classes that are not patched.
- **Gemini automatic function calling records one call.** When the SDK runs tools automatically, the whole exchange is a single `llm_end` with the usage of the **last** model call only; the intermediate model calls' tokens and cost are not counted.
