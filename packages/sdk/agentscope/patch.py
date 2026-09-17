import functools
import importlib
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agentscope._pricing import calculate_cost
from agentscope.decorators import current_parent_run_id, get_global_client
from agentscope.exceptions import AgentScopeError

logger = logging.getLogger(__name__)

# Undocumented module path whose classes we patch. It is checked explicitly so an
# incompatible SDK layout fails loudly instead of silently doing nothing.
_CHAT_COMPLETIONS_MODULE = "openai.resources.chat.completions"

_original_methods: Dict[str, Callable[..., Any]] = {}
_is_patched = False


def _extract_prompts(messages: Any) -> List[str]:
    if not messages:
        return []
    if isinstance(messages, str):
        return [messages]
    if isinstance(messages, list):
        prompts = []
        for m in messages:
            if isinstance(m, dict):
                role = m.get("role", "user")
                content = m.get("content", "")
                prompts.append(f"{role}: {content}")
            elif hasattr(m, "content"):
                role = getattr(m, "role", "user")
                prompts.append(f"{role}: {getattr(m, 'content', '')}")
            else:
                prompts.append(str(m))
        return prompts
    return [str(messages)]


def _extract_completion(response: Any) -> str:
    try:
        if hasattr(response, "choices") and response.choices:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):
                return str(choice.message.content or "")
            if isinstance(choice, dict):
                msg = choice.get("message", {})
                return str(msg.get("content", ""))
    except Exception:
        pass
    return str(response)


def _extract_token_usage(
    response: Any,
) -> tuple[Optional[int], Optional[int], Optional[int]]:
    p_tokens = None
    c_tokens = None
    t_tokens = None
    try:
        if isinstance(response, dict):
            usage_dict = response.get("usage") or {}
            p_tokens = usage_dict.get("prompt_tokens")
            c_tokens = usage_dict.get("completion_tokens")
            t_tokens = usage_dict.get("total_tokens")
        else:
            usage = getattr(response, "usage", None)
            if usage:
                p_tokens = getattr(usage, "prompt_tokens", None)
                c_tokens = getattr(usage, "completion_tokens", None)
                t_tokens = getattr(usage, "total_tokens", None)
    except Exception:
        pass
    if t_tokens is None and p_tokens is not None and c_tokens is not None:
        t_tokens = p_tokens + c_tokens
    return p_tokens, c_tokens, t_tokens


def _extract_chunk_delta(chunk: Any) -> str:
    """Return the text delta carried by a streaming ChatCompletionChunk."""
    try:
        choices = getattr(chunk, "choices", None)
        if choices:
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None)
            if content:
                return str(content)
    except Exception:
        pass
    return ""


class _LLMCallTrace:
    """Emits the llm_start / llm_end / llm_error events for one OpenAI call."""

    def __init__(self, kwargs: Dict[str, Any]):
        self.client = None
        try:
            self.client = get_global_client()
        except Exception:
            pass

        self.model = kwargs.get("model", "openai-model")
        self.prompts = _extract_prompts(kwargs.get("messages", []))
        self.temperature = kwargs.get("temperature")
        self.streaming = bool(kwargs.get("stream", False))
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
                    "agent_name": f"OpenAI:{self.model}",
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
    ) -> None:
        if self._finished:
            return
        self._finished = True
        try:
            cost_usd = calculate_cost(self.model, prompt_tokens, completion_tokens)
        except ValueError:
            cost_usd = 0.0
        self._emit(
            "llm_end",
            "completed",
            {
                "completion": completion,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "cost_usd": cost_usd,
            },
            self._latency(),
        )

    def end_from_response(self, response: Any) -> None:
        self.end(_extract_completion(response), *_extract_token_usage(response))

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


class _StreamAccumulator:
    """Collects streamed deltas and usage so llm_end can fire on exhaustion."""

    def __init__(self, trace: _LLMCallTrace):
        self.trace = trace
        self.parts: List[str] = []
        self.usage: tuple[Optional[int], Optional[int], Optional[int]] = (
            None,
            None,
            None,
        )

    def add(self, chunk: Any) -> None:
        self.parts.append(_extract_chunk_delta(chunk))
        # Usage is only present on the final chunk when the caller requests
        # stream_options={"include_usage": True}.
        if getattr(chunk, "usage", None):
            self.usage = _extract_token_usage(chunk)

    def finish(self) -> None:
        self.trace.end("".join(self.parts), *self.usage)


class _TracedStream:
    """Proxy for openai.Stream that emits llm_end once the stream is consumed."""

    def __init__(self, stream: Any, trace: _LLMCallTrace):
        self._stream = stream
        self._acc = _StreamAccumulator(trace)

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

    def __enter__(self) -> "_TracedStream":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            # A stream closed early still records what was received.
            self._acc.finish()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


class _TracedAsyncStream:
    """Proxy for openai.AsyncStream that emits llm_end once the stream is consumed."""

    def __init__(self, stream: Any, trace: _LLMCallTrace):
        self._stream = stream
        self._acc = _StreamAccumulator(trace)

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

    async def __aenter__(self) -> "_TracedAsyncStream":
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.close()

    async def close(self) -> None:
        try:
            await self._stream.close()
        finally:
            self._acc.finish()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def _wrap_sync_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace = _LLMCallTrace(kwargs)
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
            return _TracedStream(res, trace)
        trace.end_from_response(res)
        return res

    return patched_create


def _wrap_async_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    async def patched_create(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace = _LLMCallTrace(kwargs)
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
            return _TracedAsyncStream(res, trace)
        trace.end_from_response(res)
        return res

    return patched_create


def patch_openai() -> bool:
    """Patch the official OpenAI SDK to automatically stream telemetry to AgentScope.

    Patching is applied to ``Completions.create`` and ``AsyncCompletions.create``
    at the class level, so it affects every OpenAI client in the process until
    :func:`unpatch_openai` is called.

    Returns:
        True once the SDK is patched, False if ``openai`` is not installed.

    Raises:
        AgentScopeError: If the installed OpenAI SDK does not expose the
            expected chat completions classes.
    """
    global _is_patched
    if _is_patched:
        return True

    try:
        openai = importlib.import_module("openai")
    except ImportError:
        logger.warning(
            "OpenAI package not installed. Skipping agentscope.patch_openai()."
        )
        return False

    version = getattr(openai, "__version__", "unknown")
    try:
        chat_module = importlib.import_module(_CHAT_COMPLETIONS_MODULE)
    except ImportError as e:
        raise AgentScopeError(
            f"Cannot patch openai {version}: module {_CHAT_COMPLETIONS_MODULE!r} "
            "was not found. This OpenAI SDK version is not supported."
        ) from e

    missing = [
        name
        for name in ("Completions", "AsyncCompletions")
        if not callable(getattr(getattr(chat_module, name, None), "create", None))
    ]
    if missing:
        raise AgentScopeError(
            f"Cannot patch openai {version}: {', '.join(missing)}.create not found "
            f"in {_CHAT_COMPLETIONS_MODULE!r}. This OpenAI SDK version is not "
            "supported."
        )

    _original_methods["sync_create"] = chat_module.Completions.create
    _original_methods["async_create"] = chat_module.AsyncCompletions.create
    chat_module.Completions.create = _wrap_sync_create(_original_methods["sync_create"])
    chat_module.AsyncCompletions.create = _wrap_async_create(
        _original_methods["async_create"]
    )

    _is_patched = True
    logger.info(f"OpenAI SDK {version} patched for AgentScope telemetry.")
    return True


def unpatch_openai() -> None:
    """Restore the original OpenAI sync and async ``create`` methods."""
    global _is_patched
    if _original_methods:
        try:
            chat_module = importlib.import_module(_CHAT_COMPLETIONS_MODULE)
            if "sync_create" in _original_methods:
                chat_module.Completions.create = _original_methods.pop("sync_create")
            if "async_create" in _original_methods:
                chat_module.AsyncCompletions.create = _original_methods.pop(
                    "async_create"
                )
        except Exception as e:
            logger.warning(f"Failed to restore original OpenAI methods: {e}")
    _is_patched = False
