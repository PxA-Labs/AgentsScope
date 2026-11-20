"""Auto-instrumentation for the official Anthropic Python SDK.

Patches, at class level (affecting every client in the process):

* ``Messages.create`` / ``AsyncMessages.create``, including ``stream=True``
* ``Messages.stream`` / ``AsyncMessages.stream`` (the streaming helper, which
  does not go through ``create``)
"""

import functools
import importlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from agentscope.decorators import current_parent_run_id, get_global_client
from agentscope.exceptions import AgentScopeError
from agentscope.providers._base import (
    LLMCallTrace,
    ProviderAdapter,
    Usage,
    complete_usage,
    wrap_async,
    wrap_sync,
)

logger = logging.getLogger(__name__)

_MESSAGES_MODULE = "anthropic.resources.messages"
_original_methods: Dict[str, Callable[..., Any]] = {}
_is_patched = False


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _block_text(block: Any) -> str:
    """Render one content block (request or response) as text."""
    if isinstance(block, str):
        return block
    block_type = _field(block, "type")
    if block_type == "text":
        return str(_field(block, "text", ""))
    if block_type == "tool_use":
        tool_input = _field(block, "input", {})
        try:
            rendered = json.dumps(tool_input, default=str, sort_keys=True)
        except (TypeError, ValueError):
            rendered = str(tool_input)
        return f"[tool_use {_field(block, 'name', '')}: {rendered}]"
    if block_type == "tool_result":
        return f"[tool_result {_field(block, 'tool_use_id', '')}]"
    if block_type in ("image", "document"):
        return f"[{block_type}]"
    if block_type in ("thinking", "redacted_thinking"):
        # Reasoning content is not part of the visible completion.
        return ""
    return f"[{block_type}]" if block_type else str(block)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return "".join(_block_text(b) for b in content)
    return str(content)


def _extract_prompts(kwargs: Dict[str, Any]) -> List[str]:
    prompts: List[str] = []
    system = kwargs.get("system")
    if system:
        prompts.append(f"system: {_content_text(system)}")
    for message in kwargs.get("messages") or []:
        role = _field(message, "role", "user")
        prompts.append(f"{role}: {_content_text(_field(message, 'content', ''))}")
    return prompts


def _usage_from(usage: Any) -> Usage:
    if usage is None:
        return None, None, None
    return complete_usage(_field(usage, "input_tokens"), _field(usage, "output_tokens"))


_CACHE_FIELDS = ("cache_creation_input_tokens", "cache_read_input_tokens")


def _cache_details(usage: Any) -> Dict[str, Any]:
    if usage is None:
        return {}
    return {
        name: value
        for name in _CACHE_FIELDS
        if (value := _field(usage, name)) is not None
    }


class _AnthropicAdapter(ProviderAdapter):
    name = "Anthropic"
    default_model = "anthropic-model"

    def prompts(self, kwargs: Dict[str, Any]) -> List[str]:
        return _extract_prompts(kwargs)

    def completion(self, response: Any) -> str:
        return _content_text(_field(response, "content"))

    def usage(self, response: Any) -> Usage:
        # input_tokens excludes prompt-cache reads/writes, which are billed at
        # different rates; they are reported separately in usage_details.
        return _usage_from(_field(response, "usage"))

    def usage_details(self, response: Any) -> Dict[str, Any]:
        return _cache_details(_field(response, "usage"))

    def chunk_delta(self, chunk: Any) -> str:
        if _field(chunk, "type") != "content_block_delta":
            return ""
        delta = _field(chunk, "delta")
        if _field(delta, "type") == "text_delta":
            return str(_field(delta, "text", ""))
        return ""

    def chunk_usage(self, chunk: Any, current: Usage) -> Usage:
        prompt, completion, _ = current
        chunk_type = _field(chunk, "type")
        if chunk_type == "message_start":
            usage = _field(_field(chunk, "message"), "usage")
            prompt = _field(usage, "input_tokens", prompt)
            completion = _field(usage, "output_tokens", completion)
        elif chunk_type == "message_delta":
            # message_delta usage is cumulative for the response.
            completion = _field(_field(chunk, "usage"), "output_tokens", completion)
        else:
            return current
        return complete_usage(prompt, completion)

    def chunk_usage_details(
        self, chunk: Any, current: Dict[str, Any]
    ) -> Dict[str, Any]:
        if _field(chunk, "type") != "message_start":
            return current
        return {**current, **_cache_details(_field(_field(chunk, "message"), "usage"))}


_ADAPTER = _AnthropicAdapter()


def _client() -> Any:
    return get_global_client()


class _TracedMessageStreamManager:
    """Wraps ``MessageStreamManager`` returned by ``messages.stream(...)``.

    The final message snapshot (text + usage) is recorded when the ``with``
    block exits, whether or not the caller consumed the whole stream.
    """

    def __init__(self, manager: Any, trace: LLMCallTrace):
        self._manager = manager
        self._trace = trace
        self._stream: Any = None

    def _finish(self, exc: Optional[BaseException]) -> None:
        snapshot = None
        try:
            snapshot = self._stream.current_message_snapshot
        except Exception:
            pass
        if exc is not None:
            # The API call succeeded if the final message arrived (message_delta
            # sets stop_reason); an exception after that came from the caller's
            # own code in the with block, so record the response, not an error.
            if _field(snapshot, "stop_reason") is None:
                self._trace.error(exc)
                return
        if snapshot is None:
            self._trace.end("", None, None, None)
        else:
            self._trace.end_from_response(snapshot)

    def __enter__(self) -> Any:
        token = current_parent_run_id.set(self._trace.run_id)
        try:
            self._stream = self._manager.__enter__()
        except Exception as e:
            self._trace.error(e)
            raise
        finally:
            current_parent_run_id.reset(token)
        return self._stream

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        try:
            return self._manager.__exit__(exc_type, exc, tb)
        finally:
            self._finish(exc)

    async def __aenter__(self) -> Any:
        token = current_parent_run_id.set(self._trace.run_id)
        try:
            self._stream = await self._manager.__aenter__()
        except Exception as e:
            self._trace.error(e)
            raise
        finally:
            current_parent_run_id.reset(token)
        return self._stream

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> Any:
        try:
            return await self._manager.__aexit__(exc_type, exc, tb)
        finally:
            self._finish(exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)


def _wrap_stream_helper(orig: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(orig)
    def traced(self: Any, *args: Any, **kwargs: Any) -> Any:
        trace = LLMCallTrace(_ADAPTER, kwargs, _client, streaming=True)
        trace.start()
        try:
            manager = orig(self, *args, **kwargs)
        except Exception as e:
            trace.error(e)
            raise
        return _TracedMessageStreamManager(manager, trace)

    return traced


_TARGETS = (
    ("Messages", "create", wrap_sync),
    ("AsyncMessages", "create", wrap_async),
    ("Messages", "stream", None),
    ("AsyncMessages", "stream", None),
)


def patch_anthropic() -> bool:
    """Patch the Anthropic SDK to stream telemetry to AgentScope.

    Returns:
        True once patched, False if ``anthropic`` is not installed.

    Raises:
        AgentScopeError: If the installed SDK does not expose the expected
            ``Messages`` / ``AsyncMessages`` methods.
    """
    global _is_patched
    if _is_patched:
        return True

    try:
        anthropic = importlib.import_module("anthropic")
    except ImportError:
        logger.warning(
            "Anthropic package not installed. Skipping agentscope.patch_anthropic()."
        )
        return False

    version = getattr(anthropic, "__version__", "unknown")
    try:
        module = importlib.import_module(_MESSAGES_MODULE)
    except ImportError as e:
        raise AgentScopeError(
            f"Cannot patch anthropic {version}: module {_MESSAGES_MODULE!r} not "
            "found. This Anthropic SDK version is not supported."
        ) from e

    missing = [
        f"{cls}.{method}"
        for cls, method, _ in _TARGETS
        if not callable(getattr(getattr(module, cls, None), method, None))
    ]
    if missing:
        raise AgentScopeError(
            f"Cannot patch anthropic {version}: {', '.join(missing)} not found in "
            f"{_MESSAGES_MODULE!r}. This Anthropic SDK version is not supported."
        )

    for cls_name, method, wrapper in _TARGETS:
        cls = getattr(module, cls_name)
        orig = getattr(cls, method)
        _original_methods[f"{cls_name}.{method}"] = orig
        if wrapper is None:
            setattr(cls, method, _wrap_stream_helper(orig))
        else:
            setattr(cls, method, wrapper(orig, _ADAPTER, _client))

    _is_patched = True
    logger.info(f"Anthropic SDK {version} patched for AgentScope telemetry.")
    return True


def unpatch_anthropic() -> None:
    """Restore the original Anthropic SDK methods."""
    global _is_patched
    if _original_methods:
        try:
            module = importlib.import_module(_MESSAGES_MODULE)
            for key in list(_original_methods):
                cls_name, method = key.split(".")
                setattr(getattr(module, cls_name), method, _original_methods.pop(key))
        except Exception as e:
            logger.warning(f"Failed to restore original Anthropic methods: {e}")
    _is_patched = False
