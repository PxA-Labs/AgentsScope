"""Provider-agnostic machinery for auto-instrumenting LLM SDK calls.

Each provider module supplies a :class:`ProviderAdapter` that knows how to read
the model, prompts and usage out of that SDK's requests and responses. The
classes here turn one call into ``llm_start`` / ``llm_end`` / ``llm_error``
events, including for streamed responses, so every provider behaves the same.
"""

import functools
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentscope._pricing import calculate_cost
from agentscope.decorators import current_parent_run_id

Usage = Tuple[Optional[int], Optional[int], Optional[int]]
EMPTY_USAGE: Usage = (None, None, None)


def complete_usage(prompt: Optional[int], completion: Optional[int]) -> Usage:
    total = None
    if prompt is not None and completion is not None:
        total = prompt + completion
    return prompt, completion, total


class ProviderAdapter:
    """Describes how to read one SDK's requests, responses and stream chunks.

    Subclasses override the extractors they need; every extractor must be
    defensive and never raise, because tracing must not break the user's call.
    """

    #: Prefix used for the event's agent_name, e.g. "OpenAI" -> "OpenAI:gpt-4o".
    name = "LLM"
    default_model = "unknown-model"

    def model(self, kwargs: Dict[str, Any]) -> str:
        return str(kwargs.get("model") or self.default_model)

    def prompts(self, kwargs: Dict[str, Any]) -> List[str]:
        return []

    def temperature(self, kwargs: Dict[str, Any]) -> Optional[float]:
        return kwargs.get("temperature")

    def is_streaming(self, kwargs: Dict[str, Any]) -> bool:
        return bool(kwargs.get("stream", False))

    def completion(self, response: Any) -> str:
        return str(response)

    def usage(self, response: Any) -> Usage:
        return EMPTY_USAGE

    def chunk_delta(self, chunk: Any) -> str:
        return ""

    def chunk_usage(self, chunk: Any, current: Usage) -> Usage:
        """Return usage after seeing ``chunk`` (default: keep ``current``)."""
        return current

    def usage_details(self, response: Any) -> Dict[str, Any]:
        """Provider-specific usage fields (e.g. cache tokens) for the payload."""
        return {}

    def chunk_usage_details(
        self, chunk: Any, current: Dict[str, Any]
    ) -> Dict[str, Any]:
        return current


class LLMCallTrace:
    """Emits the llm_start / llm_end / llm_error events for one SDK call."""

    def __init__(
        self,
        adapter: ProviderAdapter,
        kwargs: Dict[str, Any],
        client_getter: Callable[[], Any],
        streaming: Optional[bool] = None,
    ):
        self.adapter = adapter
        self.client = None
        try:
            self.client = client_getter()
        except Exception:
            pass

        self.model = _safe(lambda: adapter.model(kwargs), adapter.default_model)
        self.prompts = _safe(lambda: adapter.prompts(kwargs), [])
        self.temperature = _safe(lambda: adapter.temperature(kwargs), None)
        self.streaming = (
            streaming
            if streaming is not None
            else _safe(lambda: adapter.is_streaming(kwargs), False)
        )
        self.run_id = str(uuid.uuid4())
        self.parent_id = current_parent_run_id.get()
        self.start_time = time.perf_counter()
        self._finished = False

    def _emit(
        self,
        event_type: str,
        status: str,
        payload: Dict[str, Any],
        latency_ms: Optional[int],
    ) -> None:
        if not self.client:
            return
        try:
            self.client.emit(
                {
                    "event_id": self.run_id,
                    "session_id": "",
                    "parent_event_id": self.parent_id,
                    "event_type": event_type,
                    "agent_name": f"{self.adapter.name}:{self.model}",
                    "agent_type": "llm",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "latency_ms": latency_ms,
                    "status": status,
                    "payload": {
                        "model": self.model,
                        "prompts": self.prompts,
                        "temperature": self.temperature,
                        "streaming": self.streaming,
                        **payload,
                    },
                }
            )
        except Exception:
            pass

    def _latency(self) -> int:
        return int((time.perf_counter() - self.start_time) * 1000)

    def start(self) -> None:
        self.start_time = time.perf_counter()
        self._emit(
            "llm_start",
            "running",
            {
                "completion": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            },
            None,
        )

    def end(
        self,
        completion: str,
        prompt_tokens: Optional[int],
        completion_tokens: Optional[int],
        total_tokens: Optional[int],
        usage_details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            cost_usd = calculate_cost(self.model, prompt_tokens, completion_tokens)
        except ValueError:
            cost_usd = 0.0
        payload: Dict[str, Any] = {
            "completion": completion,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "cost_usd": cost_usd,
        }
        if usage_details:
            payload["usage_details"] = usage_details
        self._emit("llm_end", "completed", payload, self._latency())

    def end_from_response(self, response: Any) -> None:
        completion = _safe(lambda: self.adapter.completion(response), "")
        usage = _safe(lambda: self.adapter.usage(response), EMPTY_USAGE)
        details = _safe(lambda: self.adapter.usage_details(response), {})
        self.end(completion, *usage, usage_details=details)

    def error(self, exc: BaseException) -> None:
        if self._finished:
            return
        self._finished = True
        self._emit(
            "llm_error",
            "error",
            {"completion": None, "error": str(exc)},
            self._latency(),
        )


class StreamAccumulator:
    """Collects streamed deltas and usage so llm_end can fire on exhaustion."""

    def __init__(self, trace: LLMCallTrace):
        self.trace = trace
        self.parts: List[str] = []
        self.usage: Usage = EMPTY_USAGE
        self.details: Dict[str, Any] = {}

    def add(self, chunk: Any) -> None:
        adapter = self.trace.adapter
        self.parts.append(_safe(lambda: adapter.chunk_delta(chunk), ""))
        self.usage = _safe(lambda: adapter.chunk_usage(chunk, self.usage), self.usage)
        self.details = _safe(
            lambda: adapter.chunk_usage_details(chunk, self.details), self.details
        )

    def finish(self) -> None:
        self.trace.end("".join(self.parts), *self.usage, usage_details=self.details)


class TracedStream:
    """Proxy for a sync stream that emits llm_end once the stream is consumed."""

    def __init__(self, stream: Any, trace: LLMCallTrace):
        self._stream = stream
        self._acc = StreamAccumulator(trace)

    def __iter__(self) -> Any:
        try:
            for chunk in self._stream:
                self._acc.add(chunk)
                yield chunk
        except GeneratorExit:
            # Consumer stopped iterating early; record what was received.
            self._acc.finish()
            raise
        except Exception as e:
            self._acc.trace.error(e)
            raise
        self._acc.finish()

    def __next__(self) -> Any:
        try:
            chunk = next(self._stream)
        except StopIteration:
            self._acc.finish()
            raise
        except Exception as e:
            self._acc.trace.error(e)
            raise
        self._acc.add(chunk)
        return chunk

    def __enter__(self) -> "TracedStream":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            close = getattr(self._stream, "close", None)
            if close is not None:
                close()
        finally:
            # A stream closed early still records what was received.
            self._acc.finish()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class TracedAsyncStream:
    """Proxy for an async stream that emits llm_end once the stream is consumed."""

    def __init__(self, stream: Any, trace: LLMCallTrace):
        self._stream = stream
        self._acc = StreamAccumulator(trace)

    async def __aiter__(self) -> Any:
        try:
            async for chunk in self._stream:
                self._acc.add(chunk)
                yield chunk
        except GeneratorExit:
            self._acc.finish()
            raise
        except Exception as e:
            self._acc.trace.error(e)
            raise
        self._acc.finish()

    async def __anext__(self) -> Any:
        try:
            chunk = await self._stream.__anext__()
        except StopAsyncIteration:
            self._acc.finish()
            raise
        except Exception as e:
            self._acc.trace.error(e)
            raise
        self._acc.add(chunk)
        return chunk

    async def __aenter__(self) -> "TracedAsyncStream":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    async def close(self) -> None:
        try:
            # SDK stream objects expose close(); plain async generators aclose().
            close = getattr(self._stream, "close", None) or getattr(
                self._stream, "aclose", None
            )
            if close is not None:
                await close()
        finally:
            self._acc.finish()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def wrap_sync(
    orig: Callable[..., Any],
    adapter: ProviderAdapter,
    client_getter: Callable[[], Any],
    force_streaming: bool = False,
) -> Callable[..., Any]:
    """Wrap a sync SDK method (``self, *args, **kwargs``) with tracing."""

    @functools.wraps(orig)
    def traced(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace = LLMCallTrace(
            adapter, kwargs, client_getter, streaming=True if force_streaming else None
        )
        token = current_parent_run_id.set(trace.run_id)
        trace.start()
        try:
            res = orig(self, *args, **kwargs)
        except Exception as e:
            trace.error(e)
            raise
        finally:
            current_parent_run_id.reset(token)
        if trace.streaming:
            return TracedStream(res, trace)
        trace.end_from_response(res)
        return res

    traced.__agentscope_original__ = orig  # type: ignore[attr-defined]
    return traced


def wrap_async(
    orig: Callable[..., Any],
    adapter: ProviderAdapter,
    client_getter: Callable[[], Any],
    force_streaming: bool = False,
) -> Callable[..., Any]:
    """Wrap an async SDK method (``async def self, *args, **kwargs``)."""

    @functools.wraps(orig)
    async def traced(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace = LLMCallTrace(
            adapter, kwargs, client_getter, streaming=True if force_streaming else None
        )
        token = current_parent_run_id.set(trace.run_id)
        trace.start()
        try:
            res = await orig(self, *args, **kwargs)
        except Exception as e:
            trace.error(e)
            raise
        finally:
            current_parent_run_id.reset(token)
        if trace.streaming:
            return TracedAsyncStream(res, trace)
        trace.end_from_response(res)
        return res

    traced.__agentscope_original__ = orig  # type: ignore[attr-defined]
    return traced


def _safe(fn: Callable[[], Any], default: Any) -> Any:
    try:
        return fn()
    except Exception:
        return default
