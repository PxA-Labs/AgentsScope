# LlamaIndex integration

For `llama-index-core` **0.14+** (Python 3.11+). Install with `pip install -e "packages/sdk[llamaindex]"`.

```python
from agentscope.decorators import configure
from agentscope.integrations.llamaindex import instrument_llamaindex, uninstrument_llamaindex

configure(session_name="rag-app")   # server host/port, session name
instrument_llamaindex()             # once per process (idempotent)

response = index.as_query_engine().query("What is the capital of France?")
```

This uses LlamaIndex's **instrumentation module** (a span handler plus an event handler on the root dispatcher), not the legacy `CallbackManager`. `uninstrument_llamaindex()` removes the handlers.

Events go to the global client from `configure()`, looked up on every event, so calling `configure()` again later redirects them. `instrument_llamaindex(agentscope_client=...)` sends them to a client of your own instead; calling it again with a different client switches to that one.

## What you see

| LlamaIndex | Node | Details |
|---|---|---|
| query engine `query` / `aquery` | `query` chain | query text in, response out |
| retriever `retrieve` | retriever | query, plus retrieved **documents** with content (≤1,000 chars), metadata, `score` and `node_id` (up to 20) |
| response synthesizer | `synthesizer` chain | |
| reranker | `reranker` chain | candidates, `top_n`, reranked documents |
| LLM `chat` / `complete` (and streaming) | llm | prompts, completion, token usage and cost **when the LLM reports usage** |

A typical RAG query renders as **query → retriever** and **query → synthesizer → llm**. Nodes attach to their nearest shown ancestor in LlamaIndex's span tree. A query run inside an `@trace` function nests under it.

- **Errors**: when a step raises, LlamaIndex emits no end events. Any node still open is shown as an error with the exception message.
- **One node per LLM call**: when an LLM implements `chat()` on top of `complete()` (as completion-only models do), or `astream_complete()` / `astream_chat()` by running the sync stream inside the async one (as `CustomLLM` and `MockLLM` do), the nested call is folded into one node, and its token usage is used if the outer call reports none. Other calls you make on the same LLM while a stream is open stay separate nodes.
- **Usage**: read from `additional_kwargs` (`prompt_tokens`/`completion_tokens`, as the OpenAI integration reports) or `raw.usage` (`input_tokens`/`output_tokens` as well). LLMs that report no usage show no tokens. Nothing is estimated.

## Streaming

- Your stream is never consumed by tracing. The query node records `[streaming response]` until you've read it.
- The LLM completion is assembled from the streamed deltas, exactly what your code received, and the node is marked `streaming: true`.
- The LLM node ends when the stream does. If the stream raises part-way, the node is an error. If you stop reading early, or drop a stream without reading it, the node is closed with `closed_early: true` and whatever text was received, once Python closes or garbage-collects the stream.
- **Limitation:** for a streamed query, the LLM call runs while you consume the stream, after the query has returned. LlamaIndex reports that call without a parent, so its node appears at the top level. Wrap the request in an `@trace` function to group everything under one node:

  ```python
  @trace(name="rag_request")
  def answer(q):
      return "".join(query_engine.query(q).response_gen)
  ```

## Not covered yet

- Agents and workflows (`AgentWorkflow`, `FunctionAgent`): their tool calls aren't mapped to tool nodes. LLM calls made inside them are still traced.
- Embedding calls aren't shown as nodes. They're frequent and carry no text worth inspecting.
- Span bookkeeping (and the set of open nodes) is capped at 10,000 entries per process, with the oldest forgotten first, so very old in-flight operations may lose their parent link.

> **Note:** until [#294](https://github.com/PxA-Labs/AgentsScope/issues/294) is fixed, call `get_global_client().stop()` only after giving queued events a moment to send (or keep the process alive). On `main`, `stop()` discards queued events and a connected process doesn't exit on its own.
