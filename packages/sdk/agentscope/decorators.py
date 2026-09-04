import contextvars
import functools
import inspect
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

try:
    from agentscope._pricing import estimate_tokens
except ImportError:

    def estimate_tokens(
        text: Optional[str], model_name: Optional[str] = None
    ) -> Optional[int]:
        if not text:
            return None
        return max(1, len(text) // 4)

from agentscope.client import AgentScopeClient

# ContextVar to track the hierarchy of traces in a thread/async context
current_parent_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_parent_run_id", default=None
)

_global_client: Optional[AgentScopeClient] = None


def get_global_client() -> AgentScopeClient:
    """Retrieve or initialize the global AgentScope client singleton."""
    global _global_client
    if _global_client is None:
        _global_client = AgentScopeClient()
    return _global_client


def configure(
    host: str = "localhost",
    port: int = 8765,
    session_name: Optional[str] = None,
    session_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Configure the global AgentScope client settings.

    Args:
        host: Host name of the AgentScope server.
        port: Port of the AgentScope server.
        session_name: Name of the observability session.
        session_metadata: Arbitrary tags/metadata for the session.
    """
    global _global_client
    if _global_client is not None:
        try:
            _global_client.stop()
        except Exception:
            pass
    _global_client = AgentScopeClient(
        host=host,
        port=port,
        session_name=session_name,
        session_metadata=session_metadata,
    )


def trace(
    arg: Any = None,
    name: Optional[str] = None,
    agent_type: str = "custom",
) -> Callable[..., Any]:
    """Decorator to instrument any synchronous or asynchronous Python function.

    Generates start and end/error tracing events and connects them via a
    context-aware parent_event_id.

    Usage:
        @trace
        def my_function(x):
            return x + 1

        @trace(name="custom_step", agent_type="agent")
        async def my_async_step(y):
            return y * 2
    """
    # Determine if decorator is used with or without arguments
    if callable(arg):
        # Used as @trace
        func = arg
        resolved_name = name or func.__name__
        return _make_decorator(func, resolved_name, agent_type)
    else:
        # Used as @trace(name="...", agent_type="...") or @trace("name")
        resolved_name = name or (arg if isinstance(arg, str) else None)
        return lambda f: _make_decorator(f, resolved_name or f.__name__, agent_type)


def _make_decorator(
    func: Callable[..., Any], name: str, agent_type: str
) -> Callable[..., Any]:
    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)

        # Build clean serialization of args
        inputs = {
            "args": [str(a) for a in args],
            "kwargs": {k: str(v) for k, v in kwargs.items()},
        }

        # Start Event
        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "chain_start",
                        "agent_name": name,
                        "agent_type": agent_type,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "chain_type": name,
                            "inputs": inputs,
                            "outputs": None,
                            "error": None,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            # End Event
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "chain_end",
                            "agent_name": name,
                            "agent_type": agent_type,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "chain_type": name,
                                "inputs": {},
                                "outputs": {"result": str(result)},
                                "error": None,
                            },
                        }
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)

            # Error Event
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "chain_error",
                            "agent_name": name,
                            "agent_type": agent_type,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "chain_type": name,
                                "inputs": {},
                                "outputs": None,
                                "error": str(e),
                            },
                        }
                    )
                except Exception:
                    pass
            raise e
        finally:
            current_parent_run_id.reset(token)

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)

        inputs = {
            "args": [str(a) for a in args],
            "kwargs": {k: str(v) for k, v in kwargs.items()},
        }

        # Start Event
        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "chain_start",
                        "agent_name": name,
                        "agent_type": agent_type,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "chain_type": name,
                            "inputs": inputs,
                            "outputs": None,
                            "error": None,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)  # type: ignore
            latency = int((time.perf_counter() - start_time) * 1000)

            # End Event
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "chain_end",
                            "agent_name": name,
                            "agent_type": agent_type,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "chain_type": name,
                                "inputs": {},
                                "outputs": {"result": str(result)},
                                "error": None,
                            },
                        }
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)

            # Error Event
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "chain_error",
                            "agent_name": name,
                            "agent_type": agent_type,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "chain_type": name,
                                "inputs": {},
                                "outputs": None,
                                "error": str(e),
                            },
                        }
                    )
                except Exception:
                    pass
            raise e
        finally:
            current_parent_run_id.reset(token)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def trace_llm(
    arg: Any = None,
    name: Optional[str] = None,
    model: Optional[str] = None,
) -> Callable[..., Any]:
    """Decorator to instrument custom LLM functions with LLMPayload.

    Usage:
        @trace_llm(model="gpt-4o")
        def call_my_model(prompt: str):
            return "completion text"
    """
    if callable(arg):
        func = arg
        resolved_name = name or func.__name__
        return _make_llm_decorator(func, resolved_name, model)
    else:
        resolved_name = name or (arg if isinstance(arg, str) else None)
        return lambda f: _make_llm_decorator(f, resolved_name or f.__name__, model)


def _extract_llm_prompt(
    func: Callable[..., Any], args: tuple, kwargs: dict
) -> list[str]:
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        for param in ("prompt", "prompts", "messages", "query", "input", "text"):
            if param in bound.arguments:
                val = bound.arguments[param]
                if isinstance(val, list):
                    return [str(item) for item in val]
                return [str(val)]
    except Exception:
        pass
    if args:
        return [str(args[0])]
    if kwargs:
        return [f"{k}: {v}" for k, v in kwargs.items()]
    return [""]


def _make_llm_decorator(
    func: Callable[..., Any], name: str, model_override: Optional[str]
) -> Callable[..., Any]:
    resolved_model = model_override or "custom-llm"

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)
        prompts = _extract_llm_prompt(func, args, kwargs)

        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "llm_start",
                        "agent_name": name,
                        "agent_type": "llm",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "model": resolved_model,
                            "prompts": prompts,
                            "completion": None,
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None,
                            "temperature": kwargs.get("temperature"),
                            "streaming": False,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            completion = ""
            if hasattr(result, "content"):
                completion = str(result.content)
            elif isinstance(result, str):
                completion = result
            elif isinstance(result, dict) and "text" in result:
                completion = str(result["text"])
            else:
                completion = str(result)

            prompt_text = "\n".join(prompts)
            p_tokens = estimate_tokens(prompt_text, resolved_model)
            c_tokens = estimate_tokens(completion, resolved_model)
            t_tokens = (p_tokens or 0) + (c_tokens or 0)

            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "llm_end",
                            "agent_name": name,
                            "agent_type": "llm",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "model": resolved_model,
                                "prompts": prompts,
                                "completion": completion,
                                "prompt_tokens": p_tokens,
                                "completion_tokens": c_tokens,
                                "total_tokens": t_tokens,
                                "temperature": kwargs.get("temperature"),
                                "streaming": False,
                            },
                        }
                    )
                except Exception:
                    pass
            return result
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
                            "agent_name": name,
                            "agent_type": "llm",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "model": resolved_model,
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

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)
        prompts = _extract_llm_prompt(func, args, kwargs)

        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "llm_start",
                        "agent_name": name,
                        "agent_type": "llm",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "model": resolved_model,
                            "prompts": prompts,
                            "completion": None,
                            "prompt_tokens": None,
                            "completion_tokens": None,
                            "total_tokens": None,
                            "temperature": kwargs.get("temperature"),
                            "streaming": False,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            completion = ""
            if hasattr(result, "content"):
                completion = str(result.content)
            elif isinstance(result, str):
                completion = result
            elif isinstance(result, dict) and "text" in result:
                completion = str(result["text"])
            else:
                completion = str(result)

            prompt_text = "\n".join(prompts)
            p_tokens = estimate_tokens(prompt_text, resolved_model)
            c_tokens = estimate_tokens(completion, resolved_model)
            t_tokens = (p_tokens or 0) + (c_tokens or 0)

            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "llm_end",
                            "agent_name": name,
                            "agent_type": "llm",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "model": resolved_model,
                                "prompts": prompts,
                                "completion": completion,
                                "prompt_tokens": p_tokens,
                                "completion_tokens": c_tokens,
                                "total_tokens": t_tokens,
                                "temperature": kwargs.get("temperature"),
                                "streaming": False,
                            },
                        }
                    )
                except Exception:
                    pass
            return result
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
                            "agent_name": name,
                            "agent_type": "llm",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "model": resolved_model,
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

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def trace_tool(
    arg: Any = None,
    name: Optional[str] = None,
) -> Callable[..., Any]:
    """Decorator to instrument custom tool functions with ToolPayload.

    Usage:
        @trace_tool(name="calculator")
        def calculate(expression: str):
            return eval(expression)
    """
    if callable(arg):
        func = arg
        resolved_name = name or func.__name__
        return _make_tool_decorator(func, resolved_name)
    else:
        resolved_name = name or (arg if isinstance(arg, str) else None)
        return lambda f: _make_tool_decorator(f, resolved_name or f.__name__)


def _extract_tool_input(func: Callable[..., Any], args: tuple, kwargs: dict) -> str:
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        for key in ("tool_input", "input", "query", "expression", "text"):
            if key in bound.arguments:
                return str(bound.arguments[key])
        if bound.arguments:
            return str(dict(bound.arguments))
    except Exception:
        pass
    if args:
        return str(args[0])
    if kwargs:
        return str(kwargs)
    return ""


def _make_tool_decorator(
    func: Callable[..., Any], name: str
) -> Callable[..., Any]:
    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)
        tool_input = _extract_tool_input(func, args, kwargs)

        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "tool_start",
                        "agent_name": name,
                        "agent_type": "tool",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "tool_name": name,
                            "tool_input": tool_input,
                            "tool_output": None,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "tool_end",
                            "agent_name": name,
                            "agent_type": "tool",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "tool_name": name,
                                "tool_input": tool_input,
                                "tool_output": str(result),
                            },
                        }
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "tool_error",
                            "agent_name": name,
                            "agent_type": "tool",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "tool_name": name,
                                "tool_input": tool_input,
                                "error": str(e),
                            },
                        }
                    )
                except Exception:
                    pass
            raise e
        finally:
            current_parent_run_id.reset(token)

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)
        tool_input = _extract_tool_input(func, args, kwargs)

        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "tool_start",
                        "agent_name": name,
                        "agent_type": "tool",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "tool_name": name,
                            "tool_input": tool_input,
                            "tool_output": None,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "tool_end",
                            "agent_name": name,
                            "agent_type": "tool",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "tool_name": name,
                                "tool_input": tool_input,
                                "tool_output": str(result),
                            },
                        }
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "tool_error",
                            "agent_name": name,
                            "agent_type": "tool",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "tool_name": name,
                                "tool_input": tool_input,
                                "error": str(e),
                            },
                        }
                    )
                except Exception:
                    pass
            raise e
        finally:
            current_parent_run_id.reset(token)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def trace_retriever(
    arg: Any = None,
    name: Optional[str] = None,
) -> Callable[..., Any]:
    """Decorator to instrument retriever search functions.

    Usage:
        @trace_retriever(name="vector_store")
        def search(query: str):
            return ["doc1", "doc2"]
    """
    if callable(arg):
        func = arg
        resolved_name = name or func.__name__
        return _make_retriever_decorator(func, resolved_name)
    else:
        resolved_name = name or (arg if isinstance(arg, str) else None)
        return lambda f: _make_retriever_decorator(f, resolved_name or f.__name__)


def _extract_retriever_query(
    func: Callable[..., Any], args: tuple, kwargs: dict
) -> str:
    try:
        sig = inspect.signature(func)
        bound = sig.bind_partial(*args, **kwargs)
        for key in ("query", "query_str", "prompt", "text", "search"):
            if key in bound.arguments:
                return str(bound.arguments[key])
    except Exception:
        pass
    if args:
        return str(args[0])
    if kwargs:
        return str(kwargs)
    return ""


def _make_retriever_decorator(
    func: Callable[..., Any], name: str
) -> Callable[..., Any]:
    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)
        query = _extract_retriever_query(func, args, kwargs)

        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "retriever_start",
                        "agent_name": name,
                        "agent_type": "retriever",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "query": query,
                            "documents": None,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            docs = (
                [str(d) for d in result]
                if isinstance(result, list)
                else [str(result)]
            )

            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "retriever_end",
                            "agent_name": name,
                            "agent_type": "retriever",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "query": query,
                                "documents": docs,
                            },
                        }
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "retriever_error",
                            "agent_name": name,
                            "agent_type": "retriever",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "query": query,
                                "error": str(e),
                            },
                        }
                    )
                except Exception:
                    pass
            raise e
        finally:
            current_parent_run_id.reset(token)

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = None
        try:
            client = get_global_client()
        except Exception:
            pass

        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)
        query = _extract_retriever_query(func, args, kwargs)

        if client:
            try:
                client.emit(
                    {
                        "event_id": run_id,
                        "session_id": "",
                        "parent_event_id": parent_id,
                        "event_type": "retriever_start",
                        "agent_name": name,
                        "agent_type": "retriever",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "latency_ms": None,
                        "status": "running",
                        "payload": {
                            "query": query,
                            "documents": None,
                        },
                    }
                )
            except Exception:
                pass

        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            docs = (
                [str(d) for d in result]
                if isinstance(result, list)
                else [str(result)]
            )

            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "retriever_end",
                            "agent_name": name,
                            "agent_type": "retriever",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "completed",
                            "payload": {
                                "query": query,
                                "documents": docs,
                            },
                        }
                    )
                except Exception:
                    pass
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)
            if client:
                try:
                    client.emit(
                        {
                            "event_id": run_id,
                            "session_id": "",
                            "parent_event_id": parent_id,
                            "event_type": "retriever_error",
                            "agent_name": name,
                            "agent_type": "retriever",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "latency_ms": latency,
                            "status": "error",
                            "payload": {
                                "query": query,
                                "error": str(e),
                            },
                        }
                    )
                except Exception:
                    pass
            raise e
        finally:
            current_parent_run_id.reset(token)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper

