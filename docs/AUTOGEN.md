# AutoGen integration

For `autogen-agentchat` / `autogen-core` **0.4+** (tested on 0.7.5). Install with `pip install -e "packages/sdk[autogen]"`.

There are two pieces. Use both for the full picture:

| | What it records | Where it hooks in |
|---|---|---|
| `trace_model_client(client)` | every LLM call: prompts, completion (incl. function calls), tokens, cost, latency | wraps any `ChatCompletionClient` |
| `AgentScopeAutoGenTracer` | the run, each agent turn, tool calls, handoffs, termination | wraps `run_stream(...)` |

```python
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

from agentscope_trace.decorators import configure
from agentscope_trace.integrations.autogen import AgentScopeAutoGenTracer, trace_model_client

configure(session_name="autogen-team")      # server host/port, session name
model = trace_model_client(OpenAIChatCompletionClient(model="gpt-4o"))

team = RoundRobinGroupChat([
    AssistantAgent("researcher", model_client=model, tools=[...]),
    AssistantAgent("writer", model_client=model),
], termination_condition=...)

tracer = AgentScopeAutoGenTracer(name="research-team")
result = await tracer.run(team, task="Write about Paris")

# or keep your own stream consumer (e.g. Console):
await Console(tracer.run_stream(team, task="..."))

# or trace a stream you start yourself:
await Console(tracer.trace(team.run_stream(task="..."), task="..."))
```

`trace()` yields every stream item unchanged. Both pieces report to the global client from `configure()`, so they land in the same session; it is looked up on every event, so calling `configure()` again redirects clients and tracers you already created.

Stopping early (`break`, or `aclose()` on the stream) is a normal close: the run ends as `chain_end` with `closed_early: true` and the session is marked `completed`. What happens to the team depends on who started the stream:

- **`tracer.run(...)` / `tracer.run_stream(...)`**: the tracer passes a `CancellationToken` to `run_stream` (or yours, if you pass `cancellation_token=`) and cancels it, so the team stops: in-flight model calls are cancelled and no new ones start.
- **`tracer.trace(team.run_stream(...))`**: pass the same token to both, `tracer.trace(team.run_stream(task=t, cancellation_token=token), task=t, cancellation_token=token)`, and the tracer cancels it. Without a token, AutoGen's `aclose()` does **not** stop the team: it waits until the team goes idle, so the conversation can keep running (and calling the model) until its termination condition. To stop it gracefully after the current turn instead, add an `ExternalTermination` to the team and call `set()` on it before closing.

Cancellation is handled the same way. If the task awaiting the next item is cancelled (you cancel the consumer task or the `tracer.run(...)` task, or an `asyncio.timeout()` / `wait_for()` around them runs out), or the run's token is cancelled, the run ends as `chain_end` with `closed_early: true` and `cancelled: true`, and the session is marked `completed`. When the tracer has the token (the two cases above), it cancels the token before the cancellation reaches AutoGen, so the team stops instead of running on to its termination condition. Without a token, AutoGen waits for the team to go idle first, as with `aclose()`. The `CancelledError` (or a timeout's `TimeoutError`) always reaches your code unchanged.

In every case the run node is closed only after the inner stream has finished closing, so LLM calls made while the team winds down are recorded under the run, never after it ended. Cancelling a token can leave the team in an inconsistent state (AutoGen's own caveat); call `team.reset()` before reusing it if that matters.

The traced client is an AutoGen component, so agents and teams that use it can still be saved with `dump_component()`. A loaded client reports to the global client.

## What you see

- **Run node** (`agent_type="team"`): the task as input; stop reason, message count and final message as output, plus `closed_early` / `cancelled` when the run was stopped or cancelled. The session is marked `completed` / `failed` when the run ends (`mark_session_status=False` to opt out). Only an error raised by the team fails the run; stopping early and cancellation do not.
- **Agent turn nodes** (`agent_type="agent"`): one per agent response, under the run. A turn holds the agent's events (tool calls, thoughts) and ends with its chat message, which is the turn's output; if the same agent responds again, that is a new turn. Handoff targets and thoughts are included, and AutoGen's per-message `models_usage` is attached as information.
- **Tool nodes** under the turn that requested them, paired by tool-call id. Results with `is_error=True` become `tool_error`.
- **LLM nodes** from traced model clients: tokens and cost come **only** from here, so using the tracer and the wrapper together never double-counts.

## Limitations

- **LLM nodes attach to the run, not the agent turn.** The model call happens before AutoGen yields the message that reveals which agent made it. Use a separate traced client per agent and the `name=` argument if you need per-agent attribution on LLM nodes.
- **Tool latency is measured from the stream**, from when the request event is yielded to when the result event is yielded. With `reflect_on_tool_use=True` it includes the reflection call.
- Streaming token chunks (`ModelClientStreamingChunkEvent`) aren't shown individually. The final message carries the full text.
- Budgets (`budget_limit_usd`) aren't supported.
