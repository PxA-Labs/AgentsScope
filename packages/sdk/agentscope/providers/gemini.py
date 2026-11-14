"""Auto-instrumentation for the Google Gen AI SDK (``google-genai``).

Patches, at class level (affecting every ``genai.Client`` in the process):

* ``Models.generate_content`` / ``AsyncModels.generate_content``
* ``Models.generate_content_stream`` / ``AsyncModels.generate_content_stream``

These are reached as ``client.models.*`` and ``client.aio.models.*``.
"""

import importlib
import json
import logging
from typing import Any, Callable, Dict, List, Optional

from agentscope.decorators import get_global_client
from agentscope.exceptions import AgentScopeError
from agentscope.providers._base import (
    EMPTY_USAGE,
    ProviderAdapter,
    Usage,
    wrap_async,
    wrap_sync,
)

logger = logging.getLogger(__name__)

_MODELS_MODULE = "google.genai.models"
_original_methods: Dict[str, Callable[..., Any]] = {}
_is_patched = False


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if _field(part, "thought"):
        # Thought summaries are not part of the visible answer.
        return ""
    text = _field(part, "text")
    if text:
        return str(text)
    call = _field(part, "function_call")
    if call is not None:
        args = _field(call, "args", {}) or {}
        try:
            rendered = json.dumps(args, default=str, sort_keys=True)
        except (TypeError, ValueError):
            rendered = str(args)
        return f"[function_call {_field(call, 'name', '')}: {rendered}]"
    if _field(part, "function_response") is not None:
        return "[function_response]"
    if _field(part, "inline_data") is not None or _field(part, "file_data") is not None:
        return "[media]"
    return ""


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = _field(content, "parts")
    if parts is not None:
        return "".join(_part_text(p) for p in parts)
    return _part_text(content)


def _extract_prompts(kwargs: Dict[str, Any]) -> List[str]:
    prompts: List[str] = []
    system = _field(kwargs.get("config"), "system_instruction")
    if system:
        prompts.append(f"system: {_content_text(system)}")
    contents = kwargs.get("contents")
    if contents is None:
        return prompts
    if not isinstance(contents, (list, tuple)):
        contents = [contents]
    for item in contents:
        if isinstance(item, (list, tuple)):
            prompts.append(f"user: {''.join(_part_text(p) for p in item)}")
            continue
        role = _field(item, "role") if not isinstance(item, str) else None
        prompts.append(f"{role or 'user'}: {_content_text(item)}")
    return prompts


def _response_text(response: Any) -> str:
    candidates = _field(response, "candidates") or []
    if not candidates:
        return ""
    return _content_text(_field(candidates[0], "content"))


def _usage(response: Any) -> Usage:
    meta = _field(response, "usage_metadata")
    if meta is None:
        return EMPTY_USAGE
    prompt = _field(meta, "prompt_token_count")
    completion = _field(meta, "candidates_token_count")
    total = _field(meta, "total_token_count")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return prompt, completion, total


_DETAIL_FIELDS = (
    "thoughts_token_count",
    "cached_content_token_count",
    "tool_use_prompt_token_count",
)


def _usage_details(response: Any) -> Dict[str, Any]:
    meta = _field(response, "usage_metadata")
    return {
        name: value
        for name in _DETAIL_FIELDS
        if (value := _field(meta, name)) is not None
    }


class _GeminiAdapter(ProviderAdapter):
    name = "Gemini"
    default_model = "gemini-model"

    def model(self, kwargs: Dict[str, Any]) -> str:
        model = str(kwargs.get("model") or self.default_model)
        # "models/gemini-1.5-flash" -> "gemini-1.5-flash" so pricing matches.
        return model.split("/", 1)[1] if model.startswith("models/") else model

    def prompts(self, kwargs: Dict[str, Any]) -> List[str]:
        return _extract_prompts(kwargs)

    def temperature(self, kwargs: Dict[str, Any]) -> Optional[float]:
        return _field(kwargs.get("config"), "temperature")

    def is_streaming(self, kwargs: Dict[str, Any]) -> bool:
        # Streaming is a separate method (forced by the wrapper), never a kwarg.
        return False

    def completion(self, response: Any) -> str:
        return _response_text(response)

    def usage(self, response: Any) -> Usage:
        return _usage(response)

    def usage_details(self, response: Any) -> Dict[str, Any]:
        return _usage_details(response)

    def chunk_delta(self, chunk: Any) -> str:
        return _response_text(chunk)

    def chunk_usage(self, chunk: Any, current: Usage) -> Usage:
        # Each chunk's usage_metadata is cumulative; keep the latest.
        usage = _usage(chunk)
        return usage if usage != EMPTY_USAGE else current

    def chunk_usage_details(
        self, chunk: Any, current: Dict[str, Any]
    ) -> Dict[str, Any]:
        return _usage_details(chunk) or current


_ADAPTER = _GeminiAdapter()


def _client() -> Any:
    return get_global_client()


_TARGETS = (
    ("Models", "generate_content", wrap_sync, False),
    ("Models", "generate_content_stream", wrap_sync, True),
    ("AsyncModels", "generate_content", wrap_async, False),
    ("AsyncModels", "generate_content_stream", wrap_async, True),
)


def patch_gemini() -> bool:
    """Patch the Google Gen AI SDK to stream telemetry to AgentScope.

    Returns:
        True once patched, False if ``google-genai`` is not installed.

    Raises:
        AgentScopeError: If the installed SDK does not expose the expected
            ``Models`` / ``AsyncModels`` methods.
    """
    global _is_patched
    if _is_patched:
        return True

    try:
        genai = importlib.import_module("google.genai")
    except ImportError:
        logger.warning(
            "google-genai package not installed. Skipping agentscope.patch_gemini()."
        )
        return False

    version = getattr(genai, "__version__", "unknown")
    try:
        module = importlib.import_module(_MODELS_MODULE)
    except ImportError as e:
        raise AgentScopeError(
            f"Cannot patch google-genai {version}: module {_MODELS_MODULE!r} not "
            "found. This google-genai version is not supported."
        ) from e

    missing = [
        f"{cls}.{method}"
        for cls, method, _, _ in _TARGETS
        if not callable(getattr(getattr(module, cls, None), method, None))
    ]
    if missing:
        raise AgentScopeError(
            f"Cannot patch google-genai {version}: {', '.join(missing)} not found "
            f"in {_MODELS_MODULE!r}. This google-genai version is not supported."
        )

    for cls_name, method, wrapper, streaming in _TARGETS:
        cls = getattr(module, cls_name)
        orig = getattr(cls, method)
        _original_methods[f"{cls_name}.{method}"] = orig
        setattr(
            cls, method, wrapper(orig, _ADAPTER, _client, force_streaming=streaming)
        )

    _is_patched = True
    logger.info(f"google-genai {version} patched for AgentScope telemetry.")
    return True


def unpatch_gemini() -> None:
    """Restore the original google-genai methods."""
    global _is_patched
    if _original_methods:
        try:
            module = importlib.import_module(_MODELS_MODULE)
            for key in list(_original_methods):
                cls_name, method = key.split(".")
                setattr(getattr(module, cls_name), method, _original_methods.pop(key))
        except Exception as e:
            logger.warning(f"Failed to restore original google-genai methods: {e}")
    _is_patched = False
