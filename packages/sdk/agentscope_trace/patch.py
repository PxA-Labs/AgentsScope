import importlib
import importlib.util
import logging
from typing import Any, Callable, Dict, List, Optional

from agentscope_trace.decorators import get_global_client
from agentscope_trace.exceptions import AgentScopeError
from agentscope_trace.providers._base import (
    ProviderAdapter,
    Usage,
    wrap_async,
    wrap_sync,
)

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


class _OpenAIAdapter(ProviderAdapter):
    name = "OpenAI"
    default_model = "openai-model"

    def prompts(self, kwargs: Dict[str, Any]) -> List[str]:
        return _extract_prompts(kwargs.get("messages", []))

    def completion(self, response: Any) -> str:
        return _extract_completion(response)

    def usage(self, response: Any) -> Usage:
        return _extract_token_usage(response)

    def chunk_delta(self, chunk: Any) -> str:
        return _extract_chunk_delta(chunk)

    def chunk_usage(self, chunk: Any, current: Usage) -> Usage:
        # Usage is only present on the final chunk when the caller requests
        # stream_options={"include_usage": True}.
        if getattr(chunk, "usage", None):
            return _extract_token_usage(chunk)
        return current


_ADAPTER = _OpenAIAdapter()


def _client() -> Any:
    # Resolved at call time so tests can monkeypatch this module's
    # get_global_client.
    return get_global_client()


def _wrap_sync_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    return wrap_sync(orig, _ADAPTER, _client)


def _wrap_async_create(orig: Callable[..., Any]) -> Callable[..., Any]:
    return wrap_async(orig, _ADAPTER, _client)


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
            "OpenAI package not installed. Skipping agentscope_trace.patch_openai()."
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


_PROVIDERS = ("openai", "anthropic", "gemini")
_SDK_MODULES = {"openai": "openai", "anthropic": "anthropic", "gemini": "google.genai"}


def _sdk_installed(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _patch_function(provider: str) -> Callable[[], bool]:
    if provider == "openai":
        return patch_openai
    if provider == "anthropic":
        from agentscope_trace.providers.anthropic import patch_anthropic

        return patch_anthropic
    from agentscope_trace.providers.gemini import patch_gemini

    return patch_gemini


def patch_all() -> Dict[str, bool]:
    """Patch every supported provider SDK that is installed.

    SDKs that are not installed are skipped silently. An installed SDK whose
    layout is not supported is logged and reported as False instead of raising,
    so one incompatible SDK does not prevent instrumenting the others.

    Returns:
        Mapping of provider name ("openai", "anthropic", "gemini") to whether
        it is now patched.
    """
    results: Dict[str, bool] = {}
    for provider in _PROVIDERS:
        if not _sdk_installed(_SDK_MODULES[provider]):
            results[provider] = False
            continue
        try:
            results[provider] = _patch_function(provider)()
        except AgentScopeError as e:
            logger.warning(f"Skipping {provider} instrumentation: {e}")
            results[provider] = False
    return results


def unpatch_all() -> None:
    """Undo :func:`patch_all` (safe to call even if nothing was patched)."""
    from agentscope_trace.providers.anthropic import unpatch_anthropic
    from agentscope_trace.providers.gemini import unpatch_gemini

    unpatch_openai()
    unpatch_anthropic()
    unpatch_gemini()
