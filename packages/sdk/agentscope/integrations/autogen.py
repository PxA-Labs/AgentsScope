"""AutoGen (``autogen-agentchat`` / ``autogen-core`` 0.4+) integration.

Two complementary pieces, both reporting to the global AgentScope client
(configure it with ``agentscope.decorators.configure(...)``):

* :func:`trace_model_client` wraps any ``ChatCompletionClient`` and emits
  ``llm_start`` / ``llm_end`` / ``llm_error`` with prompts, completion, token
  usage and cost. It is the source of token/cost data and also works on its
  own, without teams.

* :class:`AgentScopeAutoGenTracer` wraps a team's (or agent's)
  ``run_stream(...)`` and records its structure: the run, each agent turn,
  tool calls (paired by call id) and termination. It deliberately does not
  emit token counts, so combining it with traced model clients never
  double-counts.

Usage::

    from agentscope.decorators import configure
    from agentscope.integrations.autogen import (
        AgentScopeAutoGenTracer, trace_model_client,
    )

    configure(session_name="autogen-team")
    model = trace_model_client(OpenAIChatCompletionClient(model="gpt-4o"))
    team = RoundRobinGroupChat([AssistantAgent("a", model_client=model), ...])
    result = await AgentScopeAutoGenTracer().run(team, task="...")
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Sequence

from agentscope._pricing import calculate_cost
from agentscope.decorators import current_parent_run_id, get_global_client

logger = logging.getLogger(__name__)

_MAX_TEXT = 4000


def _truncate(text: str, limit: int = _MAX_TEXT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_function_calls(calls: Sequence[Any]) -> str:
    rendered = []
    for call in calls:
        name = getattr(call, "name", "")
        arguments = getattr(call, "arguments", "")
        rendered.append(f"[function_call {name}: {arguments}]")
    return "".join(rendered)


def _content_text(content: Any) -> str:
    """Render AutoGen message/result content (str, calls, results, parts)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif hasattr(item, "arguments") and hasattr(item, "name"):
                parts.append(_render_function_calls([item]))
            elif hasattr(item, "call_id") and hasattr(item, "content"):
                parts.append(f"[function_result {getattr(item, 'name', '')}]")
            else:
                parts.append(f"[{type(item).__name__}]")
        return "".join(parts)
    return str(content)


_ROLE_BY_TYPE = {
    "SystemMessage": "system",
    "UserMessage": "user",
    "AssistantMessage": "assistant",
    "FunctionExecutionResultMessage": "tool",
}


def _render_llm_messages(messages: Sequence[Any]) -> List[str]:
    prompts = []
    for message in messages or []:
        role = _ROLE_BY_TYPE.get(type(message).__name__, type(message).__name__)
        source = getattr(message, "source", None)
        label = (
            f"{role}({source})" if source and role in ("user", "assistant") else role
        )
        prompts.append(
            _truncate(f"{label}: {_content_text(getattr(message, 'content', ''))}")
        )
    return prompts


def _model_name(client: Any) -> str:
    for candidate in (
        getattr(client, "model", None),
        (
            (getattr(client, "_raw_config", None) or {}).get("model")
            if isinstance(getattr(client, "_raw_config", None), dict)
            else None
        ),
    ):
        if isinstance(candidate, str) and candidate:
            return candidate
    try:
        family = client.model_info.get("family")
        if family:
            return str(family)
    except Exception:
        pass
    return type(client).__name__


class _Emitter:
    """Builds and sends AgentScope events (never raises)."""

    def __init__(self, client: Any = None):
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        # Resolved on every use (not cached) so a later ``configure(...)``
        # takes effect for clients and tracers created before it.
        try:
            return get_global_client()
        except Exception:
            return None

    def emit(
        self,
        event_id: str,
        event_type: str,
        agent_name: str,
        agent_type: str,
        status: str,
        payload: Dict[str, Any],
        parent_id: Optional[str],
        latency_ms: Optional[int] = None,
    ) -> None:
        client = self.client
        if client is None:
            return
        try:
            client.emit(
                {
                    "event_id": event_id,
                    "session_id": "",
                    "parent_event_id": parent_id,
                    "event_type": event_type,
                    "agent_name": agent_name,
                    "agent_type": agent_type,
                    "timestamp": _now(),
                    "latency_ms": latency_ms,
                    "status": status,
                    "payload": payload,
                }
            )
        except Exception as e:
            logger.debug(f"AgentScope AutoGen emit failed: {e}")


# --------------------------------------------------------------------------
# Model client wrapper
# --------------------------------------------------------------------------


def trace_model_client(
    client: Any, name: Optional[str] = None, agentscope_client: Any = None
) -> Any:
    """Wrap an AutoGen ``ChatCompletionClient`` so every call is traced.

    Args:
        client: Any ``autogen_core.models.ChatCompletionClient``.
        name: Model name to report (defaults to the client's model).
        agentscope_client: Override the AgentScope client (defaults to the
            global client from ``agentscope.decorators.configure``).
    """
    from autogen_core.models import ChatCompletionClient, CreateResult

    if isinstance(client, ChatCompletionClient) and getattr(
        client, "_agentscope_traced", False
    ):
        return client

    emitter = _Emitter(agentscope_client)
    model = name or _model_name(client)

    class TracedChatCompletionClient(ChatCompletionClient):
        _agentscope_traced = True

        def __init__(self) -> None:
            self._inner = client

        # -- tracing helpers ----------------------------------------------

        def _start(self, messages: Sequence[Any], streaming: bool) -> Dict[str, Any]:
            run = {
                "id": str(uuid.uuid4()),
                "parent": current_parent_run_id.get(),
                "t0": time.perf_counter(),
                "base": {
                    "model": model,
                    "prompts": _render_llm_messages(messages),
                    "streaming": streaming,
                },
            }
            emitter.emit(
                run["id"],
                "llm_start",
                model,
                "llm",
                "running",
                {**run["base"], "completion": None},
                run["parent"],
            )
            return run

        def _end(self, run: Dict[str, Any], result: Any) -> None:
            usage = getattr(result, "usage", None)
            prompt = getattr(usage, "prompt_tokens", None)
            completion = getattr(usage, "completion_tokens", None)
            total = None
            if prompt is not None and completion is not None:
                total = prompt + completion
            payload = {
                **run["base"],
                "completion": _truncate(_content_text(getattr(result, "content", ""))),
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": total,
                "finish_reason": getattr(result, "finish_reason", None),
            }
            if getattr(result, "cached", False):
                payload["cached"] = True
            if prompt is not None or completion is not None:
                try:
                    payload["cost_usd"] = calculate_cost(model, prompt, completion)
                except ValueError:
                    pass
            emitter.emit(
                run["id"],
                "llm_end",
                model,
                "llm",
                "completed",
                payload,
                run["parent"],
                int((time.perf_counter() - run["t0"]) * 1000),
            )

        def _error(self, run: Dict[str, Any], exc: BaseException) -> None:
            emitter.emit(
                run["id"],
                "llm_error",
                model,
                "llm",
                "error",
                {**run["base"], "completion": None, "error": str(exc)},
                run["parent"],
                int((time.perf_counter() - run["t0"]) * 1000),
            )

        # -- ChatCompletionClient API ---------------------------------------

        async def create(self, messages, **kwargs):  # type: ignore[override]
            run = self._start(messages, streaming=False)
            try:
                result = await self._inner.create(messages, **kwargs)
            except BaseException as e:
                self._error(run, e)
                raise
            self._end(run, result)
            return result

        async def create_stream(  # type: ignore[override]
            self, messages, **kwargs
        ) -> AsyncGenerator[Any, None]:
            run = self._start(messages, streaming=True)
            finished = False
            try:
                async for item in self._inner.create_stream(messages, **kwargs):
                    if isinstance(item, CreateResult):
                        self._end(run, item)
                        finished = True
                    yield item
            except BaseException as e:
                if not finished:
                    self._error(run, e)
                raise

        async def close(self) -> None:
            await self._inner.close()

        def actual_usage(self):  # type: ignore[override]
            return self._inner.actual_usage()

        def total_usage(self):  # type: ignore[override]
            return self._inner.total_usage()

        def count_tokens(self, messages, **kwargs):  # type: ignore[override]
            return self._inner.count_tokens(messages, **kwargs)

        def remaining_tokens(self, messages, **kwargs):  # type: ignore[override]
            return self._inner.remaining_tokens(messages, **kwargs)

        @property
        def capabilities(self):  # type: ignore[override]
            return self._inner.capabilities

        @property
        def model_info(self):  # type: ignore[override]
            return self._inner.model_info

        def __getattr__(self, item: str) -> Any:
            return getattr(self._inner, item)

    return TracedChatCompletionClient()


# --------------------------------------------------------------------------
# Team / agent run tracer
# --------------------------------------------------------------------------


class AgentScopeAutoGenTracer:
    """Record the structure of AutoGen ``run_stream`` executions.

    Args:
        name: Label for run nodes (defaults to ``"team"``).
        agentscope_client: Override the AgentScope client (defaults to the
            global client from ``agentscope.decorators.configure``).
        mark_session_status: Patch the session to ``completed`` / ``failed``
            when a run finishes.
    """

    def __init__(
        self,
        name: str = "team",
        agentscope_client: Any = None,
        mark_session_status: bool = True,
    ):
        self.name = name
        self.mark_session_status = mark_session_status
        self._emitter = _Emitter(agentscope_client)

    async def run(self, team: Any, task: Any = None, **kwargs: Any) -> Any:
        """Run ``team.run_stream(task=..., **kwargs)`` traced; return its TaskResult."""
        result = None
        async for item in self.trace(team.run_stream(task=task, **kwargs), task=task):
            result = item
        return result

    async def trace(
        self, stream: AsyncIterator[Any], task: Any = None
    ) -> AsyncGenerator[Any, None]:
        """Yield every item of ``stream`` unchanged while recording it."""
        from autogen_agentchat.base import TaskResult

        state = _RunState(self._emitter, self.name)
        state.start(task)
        iterator = stream.__aiter__()
        try:
            while True:
                # Hold the run as parent only while the inner stream is working,
                # never across our own ``yield``: the caller's context stays
                # untouched between items, and a generator abandoned mid-stream
                # (finalized later, in another Context) has nothing to reset.
                token = current_parent_run_id.set(state.run_id)
                try:
                    item = await iterator.__anext__()
                except StopAsyncIteration:
                    break
                finally:
                    current_parent_run_id.reset(token)
                try:
                    if isinstance(item, TaskResult):
                        state.finish(item)
                    else:
                        state.observe(item)
                except Exception as e:  # tracing must never break the run
                    logger.debug(f"AgentScope AutoGen tracer ignored an item: {e}")
                yield item
        except GeneratorExit:
            # The consumer stopped early (``break`` / ``aclose()``): a normal
            # close, not a failure. Close the inner stream too so the team stops.
            if not state.finished:
                state.finish(None, closed_early=True)
            self._patch("completed")
            aclose = getattr(iterator, "aclose", None)
            if aclose is not None:
                await aclose()
            raise
        except BaseException as e:
            state.fail(e)
            self._patch("failed")
            raise
        if not state.finished:
            state.finish(None)
        self._patch("completed")

    def _patch(self, status: str) -> None:
        if not self.mark_session_status:
            return
        client = self._emitter.client
        try:
            if client is not None:
                client.patch_session_status(status)
        except Exception:
            pass


class _RunState:
    """Tracks one run: open agent turn and pending tool calls."""

    def __init__(self, emitter: _Emitter, name: str):
        self.emitter = emitter
        self.name = name
        self.run_id = str(uuid.uuid4())
        self.parent_id = current_parent_run_id.get()
        self.t0 = time.perf_counter()
        self.turn: Optional[Dict[str, Any]] = None
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.message_count = 0
        self.finished = False

    # -- run ------------------------------------------------------------

    def start(self, task: Any) -> None:
        self.emitter.emit(
            self.run_id,
            "chain_start",
            self.name,
            "team",
            "running",
            {
                "chain_type": "autogen_run",
                "inputs": {"task": _truncate(_content_text(task))} if task else {},
                "outputs": None,
                "error": None,
            },
            self.parent_id,
        )

    def finish(self, result: Any, closed_early: bool = False) -> None:
        self._close_turn()
        self._close_tools(error="run finished before the tool returned")
        outputs: Dict[str, Any] = {"message_count": self.message_count}
        if closed_early:
            outputs["closed_early"] = True
        if result is not None:
            outputs["stop_reason"] = getattr(result, "stop_reason", None)
            messages = getattr(result, "messages", None) or []
            if messages:
                outputs["final_message"] = _truncate(
                    _content_text(getattr(messages[-1], "content", ""))
                )
        self.emitter.emit(
            self.run_id,
            "chain_end",
            self.name,
            "team",
            "completed",
            {
                "chain_type": "autogen_run",
                "inputs": {},
                "outputs": outputs,
                "error": None,
            },
            self.parent_id,
            int((time.perf_counter() - self.t0) * 1000),
        )
        self.finished = True

    def fail(self, exc: BaseException) -> None:
        self._close_turn(error=str(exc))
        self._close_tools(error=str(exc))
        self.emitter.emit(
            self.run_id,
            "chain_error",
            self.name,
            "team",
            "error",
            {
                "chain_type": "autogen_run",
                "inputs": {},
                "outputs": None,
                "error": str(exc),
            },
            self.parent_id,
            int((time.perf_counter() - self.t0) * 1000),
        )
        self.finished = True

    # -- messages -------------------------------------------------------

    def observe(self, item: Any) -> None:
        kind = type(item).__name__
        if kind == "ModelClientStreamingChunkEvent":
            return  # token deltas: the final message carries the full text
        source = getattr(item, "source", None) or "unknown"
        if source == "user" and self.message_count == 0 and kind == "TextMessage":
            self.message_count += 1
            return  # the task itself, already on the run node
        self.message_count += 1
        turn = self._turn_for(source)

        usage = getattr(item, "models_usage", None)
        if usage is not None:
            turn["usage"]["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            turn["usage"]["completion_tokens"] += (
                getattr(usage, "completion_tokens", 0) or 0
            )

        if kind == "ToolCallRequestEvent":
            for call in getattr(item, "content", []) or []:
                self._start_tool(call, turn)
        elif kind == "ToolCallExecutionEvent":
            for result in getattr(item, "content", []) or []:
                self._end_tool(result)
        elif kind == "HandoffMessage":
            turn["handoff"] = getattr(item, "target", None)
            turn["output"] = _content_text(getattr(item, "content", ""))
        elif hasattr(item, "content") and kind not in ("ThoughtEvent",):
            turn["output"] = _content_text(getattr(item, "content", ""))
        if kind == "ThoughtEvent":
            turn["thought"] = _content_text(getattr(item, "content", ""))
        if not kind.endswith("Event"):
            # A chat message (TextMessage, ToolCallSummaryMessage, Handoff...)
            # is the agent's response and ends its turn; events come before it.
            # A further response by the same agent then opens a new turn.
            self._close_turn()

    def _turn_for(self, source: str) -> Dict[str, Any]:
        if self.turn is not None and self.turn["source"] == source:
            return self.turn
        self._close_turn()
        self.turn = {
            "id": str(uuid.uuid4()),
            "source": source,
            "t0": time.perf_counter(),
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "output": None,
        }
        self.emitter.emit(
            self.turn["id"],
            "chain_start",
            source,
            "agent",
            "running",
            {"chain_type": "agent_turn", "inputs": {}, "outputs": None, "error": None},
            self.run_id,
        )
        return self.turn

    def _close_turn(self, error: Optional[str] = None) -> None:
        turn, self.turn = self.turn, None
        if turn is None:
            return
        outputs: Dict[str, Any] = {"output": _truncate(turn["output"] or "")}
        if any(turn["usage"].values()):
            # Informational only: token totals come from traced model clients.
            outputs["models_usage"] = turn["usage"]
        for key in ("handoff", "thought"):
            if turn.get(key):
                outputs[key] = _truncate(str(turn[key]))
        self.emitter.emit(
            turn["id"],
            "chain_error" if error else "chain_end",
            turn["source"],
            "agent",
            "error" if error else "completed",
            {
                "chain_type": "agent_turn",
                "inputs": {},
                "outputs": None if error else outputs,
                "error": error,
            },
            self.run_id,
            int((time.perf_counter() - turn["t0"]) * 1000),
        )

    # -- tools ----------------------------------------------------------

    def _start_tool(self, call: Any, turn: Dict[str, Any]) -> None:
        call_id = str(getattr(call, "id", None) or uuid.uuid4())
        name = str(getattr(call, "name", "tool"))
        arguments = getattr(call, "arguments", "")
        tool = {
            "id": str(uuid.uuid4()),
            "name": name,
            "input": _truncate(
                arguments if isinstance(arguments, str) else json.dumps(arguments)
            ),
            "parent": turn["id"],
            "t0": time.perf_counter(),
        }
        self.tools[call_id] = tool
        self.emitter.emit(
            tool["id"],
            "tool_start",
            name,
            "tool",
            "running",
            {"tool_name": name, "input": tool["input"], "output": None, "error": None},
            tool["parent"],
        )

    def _end_tool(self, result: Any) -> None:
        call_id = str(getattr(result, "call_id", ""))
        tool = self.tools.pop(call_id, None)
        if tool is None:
            return
        output = _truncate(_content_text(getattr(result, "content", "")))
        is_error = bool(getattr(result, "is_error", False))
        self.emitter.emit(
            tool["id"],
            "tool_error" if is_error else "tool_end",
            tool["name"],
            "tool",
            "error" if is_error else "completed",
            {
                "tool_name": tool["name"],
                "input": tool["input"],
                "output": None if is_error else output,
                "error": output if is_error else None,
            },
            tool["parent"],
            int((time.perf_counter() - tool["t0"]) * 1000),
        )

    def _close_tools(self, error: str) -> None:
        for tool in list(self.tools.values()):
            self.emitter.emit(
                tool["id"],
                "tool_error",
                tool["name"],
                "tool",
                "error",
                {
                    "tool_name": tool["name"],
                    "input": tool["input"],
                    "output": None,
                    "error": error,
                },
                tool["parent"],
                int((time.perf_counter() - tool["t0"]) * 1000),
            )
        self.tools.clear()
