import functools
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agentscope._pricing import calculate_cost
from agentscope.decorators import current_parent_run_id, get_global_client

logger = logging.getLogger(__name__)

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
        usage = getattr(response, "usage", None)
        if usage:
            p_tokens = getattr(usage, "prompt_tokens", None)
            c_tokens = getattr(usage, "completion_tokens", None)
            t_tokens = getattr(usage, "total_tokens", None)
        elif isinstance(response, dict) and "usage" in response:
            usage_dict = response["usage"]
            p_tokens = usage_dict.get("prompt_tokens")
            c_tokens = usage_dict.get("completion_tokens")
            t_tokens = usage_dict.get("total_tokens")
    except Exception:
        pass
    if t_tokens is None and p_tokens is not None and c_tokens is not None:
        t_tokens = p_tokens + c_tokens
    return p_tokens, c_tokens, t_tokens


def patch_openai() -> bool:
    """Patch the official OpenAI SDK to automatically stream telemetry to AgentScope."""
    global _is_patched
    if _is_patched:
        return True

    try:
        import openai.resources.chat.completions as chat_module

        # 1. Patch sync completions
        if hasattr(chat_module.Completions, "create"):
            orig_sync = chat_module.Completions.create
            _original_methods["sync_create"] = orig_sync

            @functools.wraps(orig_sync)
            def patched_sync(self: Any, *args: Any, **kwargs: Any) -> Any:
                client = None
                try:
                    client = get_global_client()
                except Exception:
                    pass

                model = kwargs.get("model", "openai-model")
                messages = kwargs.get("messages", [])
                prompts = _extract_prompts(messages)
                temperature = kwargs.get("temperature")
                streaming = kwargs.get("stream", False)

                run_id = str(uuid.uuid4())
                parent_id = current_parent_run_id.get()
                token = current_parent_run_id.set(run_id)

                if client:
                    try:
                        client.emit(
                            {
                                "event_id": run_id,
                                "session_id": "",
                                "parent_event_id": parent_id,
                                "event_type": "llm_start",
                                "agent_name": f"OpenAI:{model}",
                                "agent_type": "llm",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "latency_ms": None,
                                "status": "running",
                                "payload": {
                                    "model": model,
                                    "prompts": prompts,
                                    "completion": None,
                                    "prompt_tokens": None,
                                    "completion_tokens": None,
                                    "total_tokens": None,
                                    "temperature": temperature,
                                    "streaming": streaming,
                                },
                            }
                        )
                    except Exception:
                        pass

                start_time = time.perf_counter()
                try:
                    res = orig_sync(self, *args, **kwargs)
                    latency = int((time.perf_counter() - start_time) * 1000)

                    completion = _extract_completion(res)
                    p_tok, c_tok, t_tok = _extract_token_usage(res)
                    calculate_cost(model, p_tok, c_tok)

                    if client:
                        try:
                            client.emit(
                                {
                                    "event_id": run_id,
                                    "session_id": "",
                                    "parent_event_id": parent_id,
                                    "event_type": "llm_end",
                                    "agent_name": f"OpenAI:{model}",
                                    "agent_type": "llm",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "latency_ms": latency,
                                    "status": "completed",
                                    "payload": {
                                        "model": model,
                                        "prompts": prompts,
                                        "completion": completion,
                                        "prompt_tokens": p_tok,
                                        "completion_tokens": c_tok,
                                        "total_tokens": t_tok,
                                        "temperature": temperature,
                                        "streaming": streaming,
                                    },
                                }
                            )
                        except Exception:
                            pass
                    return res
                except Exception as e:
                    latency = int((time.perf_counter() - start_time) * 1000)
                    if client:
                        try:
                            client.emit(
                                {
                                    "event_id": run_id,
                                    "session_id": "",
                                    "parent_event_id": parent_id,
                                    "event_type": "llm_error",
                                    "agent_name": f"OpenAI:{model}",
                                    "agent_type": "llm",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "latency_ms": latency,
                                    "status": "error",
                                    "payload": {
                                        "model": model,
                                        "prompts": prompts,
                                        "completion": None,
                                        "error": str(e),
                                    },
                                }
                            )
                        except Exception:
                            pass
                    raise e
                finally:
                    current_parent_run_id.reset(token)

            chat_module.Completions.create = patched_sync

        # 2. Patch async completions
        if hasattr(chat_module.AsyncCompletions, "create"):
            orig_async = chat_module.AsyncCompletions.create
            _original_methods["async_create"] = orig_async

            @functools.wraps(orig_async)
            async def patched_async(self: Any, *args: Any, **kwargs: Any) -> Any:
                client = None
                try:
                    client = get_global_client()
                except Exception:
                    pass

                model = kwargs.get("model", "openai-model")
                messages = kwargs.get("messages", [])
                prompts = _extract_prompts(messages)
                temperature = kwargs.get("temperature")
                streaming = kwargs.get("stream", False)

                run_id = str(uuid.uuid4())
                parent_id = current_parent_run_id.get()
                token = current_parent_run_id.set(run_id)

                if client:
                    try:
                        client.emit(
                            {
                                "event_id": run_id,
                                "session_id": "",
                                "parent_event_id": parent_id,
                                "event_type": "llm_start",
                                "agent_name": f"OpenAI:{model}",
                                "agent_type": "llm",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "latency_ms": None,
                                "status": "running",
                                "payload": {
                                    "model": model,
                                    "prompts": prompts,
                                    "completion": None,
                                    "prompt_tokens": None,
                                    "completion_tokens": None,
                                    "total_tokens": None,
                                    "temperature": temperature,
                                    "streaming": streaming,
                                },
                            }
                        )
                    except Exception:
                        pass

                start_time = time.perf_counter()
                try:
                    res = await orig_async(self, *args, **kwargs)
                    latency = int((time.perf_counter() - start_time) * 1000)

                    completion = _extract_completion(res)
                    p_tok, c_tok, t_tok = _extract_token_usage(res)
                    calculate_cost(model, p_tok, c_tok)

                    if client:
                        try:
                            client.emit(
                                {
                                    "event_id": run_id,
                                    "session_id": "",
                                    "parent_event_id": parent_id,
                                    "event_type": "llm_end",
                                    "agent_name": f"OpenAI:{model}",
                                    "agent_type": "llm",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "latency_ms": latency,
                                    "status": "completed",
                                    "payload": {
                                        "model": model,
                                        "prompts": prompts,
                                        "completion": completion,
                                        "prompt_tokens": p_tok,
                                        "completion_tokens": c_tok,
                                        "total_tokens": t_tok,
                                        "temperature": temperature,
                                        "streaming": streaming,
                                    },
                                }
                            )
                        except Exception:
                            pass
                    return res
                except Exception as e:
                    latency = int((time.perf_counter() - start_time) * 1000)
                    if client:
                        try:
                            client.emit(
                                {
                                    "event_id": run_id,
                                    "session_id": "",
                                    "parent_event_id": parent_id,
                                    "event_type": "llm_error",
                                    "agent_name": f"OpenAI:{model}",
                                    "agent_type": "llm",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                    "latency_ms": latency,
                                    "status": "error",
                                    "payload": {
                                        "model": model,
                                        "prompts": prompts,
                                        "completion": None,
                                        "error": str(e),
                                    },
                                }
                            )
                        except Exception:
                            pass
                    raise e
                finally:
                    current_parent_run_id.reset(token)

            chat_module.AsyncCompletions.create = patched_async

        _is_patched = True
        logger.info("OpenAI SDK successfully patched for AgentScope telemetry.")
        return True
    except ImportError:
        logger.warning(
            "OpenAI package not installed. Skipping agentscope.patch_openai()."
        )
        return False


def unpatch_openai() -> None:
    """Restore original OpenAI methods if previously patched."""
    global _is_patched
    try:
        import openai.resources.chat.completions as chat_module

        if "sync_create" in _original_methods:
            chat_module.Completions.create = _original_methods.pop("sync_create")
        if "async_create" in _original_methods:
            chat_module.AsyncCompletions.create = _original_methods.pop("async_create")
    except Exception:
        pass
    _is_patched = False
