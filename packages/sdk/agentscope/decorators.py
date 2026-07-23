import contextvars
import functools
import inspect
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

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
        client = get_global_client()
        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)

        # Build clean serialization of args
        inputs = {
            "args": [str(a) for a in args],
            "kwargs": {k: str(v) for k, v in kwargs.items()},
        }

        # Start Event
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

        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            latency = int((time.perf_counter() - start_time) * 1000)

            # End Event
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
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)

            # Error Event
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
            raise e
        finally:
            current_parent_run_id.reset(token)

    @functools.wraps(func)
    async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
        client = get_global_client()
        run_id = str(uuid.uuid4())
        parent_id = current_parent_run_id.get()
        token = current_parent_run_id.set(run_id)

        inputs = {
            "args": [str(a) for a in args],
            "kwargs": {k: str(v) for k, v in kwargs.items()},
        }

        # Start Event
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

        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)  # type: ignore
            latency = int((time.perf_counter() - start_time) * 1000)

            # End Event
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
            return result
        except Exception as e:
            latency = int((time.perf_counter() - start_time) * 1000)

            # Error Event
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
            raise e
        finally:
            current_parent_run_id.reset(token)

    if inspect.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper
