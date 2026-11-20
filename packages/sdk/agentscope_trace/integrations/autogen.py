"""AutoGen (``autogen-agentchat`` / ``autogen-core`` 0.4+) integration.

Two complementary pieces, both reporting to the global AgentScope client
(configure it with ``agentscope_trace.decorators.configure(...)``):

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

    from agentscope_trace.decorators import configure
    from agentscope_trace.integrations.autogen import (
        AgentScopeAutoGenTracer, trace_model_client,
    )

    configure(session_name="autogen-team")
    model = trace_model_client(OpenAIChatCompletionClient(model="gpt-4o"))
    team = RoundRobinGroupChat([AssistantAgent("a", model_client=model), ...])
    result = await AgentScopeAutoGenTracer().run(team, task="...")
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Sequence

from agentscope_trace._pricing import calculate_cost
from agentscope_trace.decorators import current_parent_run_id, get_global_client

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

    The wrapper is a regular AutoGen component: ``dump_component()`` stores the
    wrapped client's config, and loading it back yields a traced client that
    reports to the global AgentScope client (an explicit ``agentscope_client``
    is not serialized).

    Args:
        client: Any ``autogen_core.models.ChatCompletionClient``.
        name: Model name to report (defaults to the client's model).
        agentscope_client: Override the AgentScope client (defaults to the
            global client from ``agentscope_trace.decorators.configure``).
    """
    from autogen_core.models import ChatCompletionClient

    if isinstance(client, ChatCompletionClient) and getattr(
        client, "_agentscope_traced", False
    ):
        return client
    return _traced_client_class()(
        client, name=name, agentscope_client=agentscope_client
    )


_TRACED_CLIENT_CLASS: Any = None


def __getattr__(attr: str) -> Any:
    # Lazily expose the class so ``load_component`` can import it by path
    # without making autogen a hard dependency of this module.
    if attr == "TracedChatCompletionClient":
        return _traced_client_class()
    raise AttributeError(f"module {__name__!r} has no attribute {attr!r}")


def _traced_client_class() -> Any:
    global _TRACED_CLIENT_CLASS
    if _TRACED_CLIENT_CLASS is not None:
        return _TRACED_CLIENT_CLASS

    from autogen_core import Component, ComponentModel
    from autogen_core.models import ChatCompletionClient, CreateResult
    from pydantic import BaseModel

    class TracedChatCompletionClientConfig(BaseModel):
        client: ComponentModel
        name: Optional[str] = None

    class TracedChatCompletionClient(
        ChatCompletionClient, Component[TracedChatCompletionClientConfig]
    ):
        """A ChatCompletionClient that reports every call to AgentScope."""

        component_type = "model"
        component_config_schema = TracedChatCompletionClientConfig
        component_provider_override = f"{__name__}.TracedChatCompletionClient"
        _agentscope_traced = True

        def __init__(
            self, client: Any, name: Optional[str] = None, agentscope_client: Any = None
        ) -> None:
            self._inner = client
            self._name = name
            self._model = name or _model_name(client)
            self._emitter = _Emitter(agentscope_client)

        def _to_config(self) -> TracedChatCompletionClientConfig:
            return TracedChatCompletionClientConfig(
                client=self._inner.dump_component(), name=self._name
            )

        @classmethod
        def _from_config(cls, config: TracedChatCompletionClientConfig) -> Any:
            return cls(ChatCompletionClient.load_component(config.client), config.name)

        # -- tracing helpers ----------------------------------------------

        def _start(self, messages: Sequence[Any], streaming: bool) -> Dict[str, Any]:
            run = {
                "id": str(uuid.uuid4()),
                "parent": current_parent_run_id.get(),
                "t0": time.perf_counter(),
                "base": {
                    "model": self._model,
                    "prompts": _render_llm_messages(messages),
                    "streaming": streaming,
                },
            }
            self._emitter.emit(
                run["id"],
                "llm_start",
                self._model,
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
                    payload["cost_usd"] = calculate_cost(
                        self._model, prompt, completion
                    )
                except ValueError:
                    pass
            self._emitter.emit(
                run["id"],
                "llm_end",
                self._model,
                "llm",
                "completed",
                payload,
                run["parent"],
                int((time.perf_counter() - run["t0"]) * 1000),
            )

        def _error(self, run: Dict[str, Any], exc: BaseException) -> None:
            self._emitter.emit(
                run["id"],
                "llm_error",
                self._model,
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
            if item == "_inner":  # not set yet (e.g. during copy/unpickle)
                raise AttributeError(item)
            return getattr(self._inner, item)

    TracedChatCompletionClient.__qualname__ = "TracedChatCompletionClient"
    TracedChatCompletionClient.__module__ = __name__
    _TRACED_CLIENT_CLASS = TracedChatCompletionClient
    return TracedChatCompletionClient


# --------------------------------------------------------------------------
# Team / agent run tracer
# --------------------------------------------------------------------------


class AgentScopeAutoGenTracer:
    """Record the structure of AutoGen ``run_stream`` executions.

    Args:
        name: Label for run nodes (defaults to ``"team"``).
        agentscope_client: Override the AgentScope client (defaults to the
            global client from ``agentscope_trace.decorators.configure``).
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
        async for item in self.run_stream(team, task=task, **kwargs):
            result = item
        return result

    def run_stream(
        self, team: Any, task: Any = None, **kwargs: Any
    ) -> AsyncGenerator[Any, None]:
        """Traced ``team.run_stream(task=..., **kwargs)`` that stops the team
        when the consumer stops early.

        A ``CancellationToken`` is passed to ``run_stream`` (yours, if given as
        ``cancellation_token=``) and cancelled on ``break`` / ``aclose()``, or
        when the task awaiting the next item is cancelled.
        """
        token = kwargs.get("cancellation_token")
        if token is None:
            from autogen_core import CancellationToken

            token = kwargs["cancellation_token"] = CancellationToken()
        return self.trace(
            team.run_stream(task=task, **kwargs), task=task, cancellation_token=token
        )

    async def trace(
        self,
        stream: AsyncIterator[Any],
        task: Any = None,
        cancellation_token: Any = None,
    ) -> AsyncGenerator[Any, None]:
        """Yield every item of ``stream`` unchanged while recording it.

        If the consumer stops early, or its task is cancelled while awaiting
        the next item, and ``cancellation_token`` is the token that was passed
        to ``run_stream``, it is cancelled so the team stops. Without one, the
        stream waits for the team to go idle. A cancellation still propagates.
        """
        from autogen_agentchat.base import TaskResult

        state = _RunState(self._emitter, self.name)
        state.start(task)
        iterator = stream.__aiter__()
        while True:
            # Hold the run as parent only while the inner stream is working,
            # never across our own ``yield``: the caller's context stays
            # untouched between items, and a generator abandoned mid-stream
            # (finalized later, in another Context) has nothing to reset.
            token = current_parent_run_id.set(state.run_id)
            try:
                item = await _next_item(iterator, cancellation_token)
            except StopAsyncIteration:
                break
            except asyncio.CancelledError:
                # The run was cancelled: our task (the consumer or
                # ``tracer.run()`` cancelled, a timeout) or the team's token.
                # Like stopping early, not a failure. ``_next_item`` has
                # already stopped the team, so this is recorded last.
                state.finish(None, closed_early=True, cancelled=True)
                self._patch("completed")
                raise
            except BaseException as e:
                # Only an error from the stream itself fails the run.
                state.fail(e)
                self._patch("failed")
                raise
            finally:
                current_parent_run_id.reset(token)
            try:
                if isinstance(item, TaskResult):
                    state.finish(item)
                else:
                    state.observe(item)
            except Exception as e:  # tracing must never break the run
                logger.debug(f"AgentScope AutoGen tracer ignored an item: {e}")
            try:
                yield item
            except BaseException:
                # Anything thrown in here comes from the consumer closing us:
                # ``break`` / ``aclose()`` (GeneratorExit), or asyncio
                # cancelling the finalizer of an abandoned stream at loop
                # shutdown (CancelledError). A normal close, not a failure.
                try:
                    await _close_inner(iterator, cancellation_token)
                finally:
                    # Only now: LLM calls made while the team wound down
                    # still belong to this run.
                    if not state.finished:
                        state.finish(None, closed_early=True)
                    self._patch("completed")
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


async def _anext(iterator: Any) -> Any:
    return await iterator.__anext__()


async def _next_item(iterator: Any, cancellation_token: Any) -> Any:
    """Await the next item of the inner stream, stopping the team if we are
    cancelled meanwhile.

    Cancelling our task throws ``CancelledError`` into the innermost await of
    AutoGen's ``run_stream``, whose ``finally`` then waits for the team to go
    idle: it runs on to its termination condition. So, when there is a token,
    the step runs in its own task behind a shield. If we are cancelled, the
    token is cancelled first, then the step (which now ends promptly) is
    awaited, and only then does the ``CancelledError`` propagate, unchanged.
    """
    if cancellation_token is None:
        return await iterator.__anext__()
    step = asyncio.ensure_future(_anext(iterator))
    try:
        return await asyncio.shield(step)
    except asyncio.CancelledError:
        cancellation_token.cancel()
        try:
            # A second cancellation of our task stops this wait (and the
            # step); the first one still propagates below.
            await step
        except BaseException:
            pass  # the stream ending because of the token, or its error
        else:
            # It produced an item before the token took effect and is paused
            # at its ``yield``: close it like an early ``break``.
            await _close_inner(iterator, cancellation_token)
        raise


async def _close_inner(iterator: Any, cancellation_token: Any) -> None:
    """Close the inner ``run_stream`` after the consumer stopped early.

    AutoGen's ``aclose()`` waits for the team to go idle; cancelling the run's
    token first makes it stop instead (in-flight calls are cancelled).
    """
    if cancellation_token is not None:
        cancellation_token.cancel()
    aclose = getattr(iterator, "aclose", None)
    if aclose is None:
        return
    task = asyncio.current_task()
    cancelling = getattr(task, "cancelling", None)
    before = cancelling() if cancelling else 0
    try:
        await aclose()
    except asyncio.CancelledError:
        # Raised by AutoGen's runtime because we cancelled the token. Swallow
        # it unless our own task was cancelled meanwhile.
        if cancellation_token is None or (cancelling and cancelling() > before):
            raise


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

    def finish(
        self, result: Any, closed_early: bool = False, cancelled: bool = False
    ) -> None:
        self._close_turn()
        self._close_tools(error="run finished before the tool returned")
        outputs: Dict[str, Any] = {"message_count": self.message_count}
        if closed_early:
            outputs["closed_early"] = True
        if cancelled:
            outputs["cancelled"] = True
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
