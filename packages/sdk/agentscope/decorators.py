import contextvars
import functools
import inspect
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from agentscope._pricing import estimate_tokens
from agentscope.client import AgentScopeClient

# ContextVar to track the hierarchy of traces in a thread/async context
current_parent_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_parent_run_id", default=None
)

_global_client: Optional[AgentScopeClient] = None

StartPayloadBuilder = Callable[[tuple, dict], Dict[str, Any]]
EndPayloadBuilder = Callable[[Dict[str, Any], Any], Dict[str, Any]]
ErrorPayloadBuilder = Callable[[Dict[str, Any], BaseException], Dict[str, Any]]


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


class _TraceRun:
    """Emits the start, end and error events for a single traced call."""

    def __init__(self, name: str, agent_type: str, event_prefix: str):
        self.name = name
        self.agent_type = agent_type
        self.event_prefix = event_prefix
        self.client: Optional[AgentScopeClient] = None
        try:
            self.client = get_global_client()
        except Exception:
            pass
        self.run_id = str(uuid.uuid4())
        self.parent_id = current_parent_run_id.get()
        self.start_time = time.perf_counter()

    def emit(
        self,
        suffix: str,
        status: str,
        payload: Dict[str, Any],
        latency_ms: Optional[int] = None,
    ) -> None:
        if not self.client:
            return
        try:
            self.client.emit(
                {
                    "event_id": self.run_id,
                    "session_id": "",
                    "parent_event_id": self.parent_id,
                    "event_type": f"{self.event_prefix}_{suffix}",
                    "agent_name": self.name,
                    "agent_type": self.agent_type,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "latency_ms": latency_ms,
                    "status": status,
                    "payload": payload,
                }
            )
        except Exception:
            pass

    def latency_ms(self) -> int:
        return int((time.perf_counter() - self.start_time) * 1000)


def _safe_build(builder: Callable[..., Dict[str, Any]], *args: Any) -> Dict[str, Any]:
    # Payload extraction must never break the user's function.
    try:
        return builder(*args)
    except Exception:
        return {}


def _make_traced_decorator(
    func: Callable[..., Any],
    name: str,
    *,
    agent_type: str,
    event_prefix: str,
    build_start_payload: StartPayloadBuilder,
    build_end_payload: EndPayloadBuilder,
    build_error_payload: ErrorPayloadBuilder,
) -> Callable[..., Any]:
    """Wrap a sync or async function with start/end/error telemetry events.

    The payload builders receive the call arguments (start), the start payload
    plus the result (end), or the start payload plus the exception (error).
    """

    def _begin(args: tuple, kwargs: dict) -> tuple[_TraceRun, Any, Dict[str, Any]]:
        run = _TraceRun(name, agent_type, event_prefix)
        token = current_parent_run_id.set(run.run_id)
        start_payload = _safe_build(build_start_payload, args, kwargs)
        run.emit("start", "running", start_payload)
        run.start_time = time.perf_counter()
        return run, token, start_payload

    def _succeed(run: _TraceRun, start_payload: Dict[str, Any], result: Any) -> None:
        latency = run.latency_ms()
        payload = _safe_build(build_end_payload, start_payload, result)
        run.emit("end", "completed", payload, latency)

    def _fail(run: _TraceRun, start_payload: Dict[str, Any], exc: Exception) -> None:
        latency = run.latency_ms()
        payload = _safe_build(build_error_payload, start_payload, exc)
        run.emit("error", "error", payload, latency)

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            run, token, start_payload = _begin(args, kwargs)
            try:
                result = await func(*args, **kwargs)
            except Exception as e:
                _fail(run, start_payload, e)
                raise
            finally:
                current_parent_run_id.reset(token)
            _succeed(run, start_payload, result)
            return result

        return async_wrapper

    @functools.wraps(func)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        run, token, start_payload = _begin(args, kwargs)
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            _fail(run, start_payload, e)
            raise
        finally:
            current_parent_run_id.reset(token)
        _succeed(run, start_payload, result)
        return result

    return sync_wrapper


def _decorator_entry(
    arg: Any,
    name: Optional[str],
    make: Callable[[Callable[..., Any], str], Callable[..., Any]],
) -> Callable[..., Any]:
    """Support both ``@decorator`` and ``@decorator(...)`` / ``@decorator("name")``."""
    if callable(arg):
        return make(arg, name or arg.__name__)
    resolved_name = name or (arg if isinstance(arg, str) else None)
    return lambda f: make(f, resolved_name or f.__name__)


def _bind_arguments(
    func: Callable[..., Any], args: tuple, kwargs: dict
) -> Dict[str, Any]:
    try:
        return dict(inspect.signature(func).bind_partial(*args, **kwargs).arguments)
    except Exception:
        return {}


# --- Generic chain trace ---


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
    return _decorator_entry(
        arg, name, lambda f, n: _make_chain_decorator(f, n, agent_type)
    )


def _make_chain_decorator(
    func: Callable[..., Any], name: str, agent_type: str
) -> Callable[..., Any]:
    return _make_traced_decorator(
        func,
        name,
        agent_type=agent_type,
        event_prefix="chain",
        build_start_payload=lambda args, kwargs: {
            "chain_type": name,
            "inputs": {
                "args": [str(a) for a in args],
                "kwargs": {k: str(v) for k, v in kwargs.items()},
            },
            "outputs": None,
            "error": None,
        },
        build_end_payload=lambda start, result: {
            "chain_type": name,
            "inputs": {},
            "outputs": {"result": str(result)},
            "error": None,
        },
        build_error_payload=lambda start, exc: {
            "chain_type": name,
            "inputs": {},
            "outputs": None,
            "error": str(exc),
        },
    )


# --- LLM trace ---


def trace_llm(
    arg: Any = None,
    name: Optional[str] = None,
    model: Optional[str] = None,
) -> Callable[..., Any]:
    """Decorator to instrument custom LLM functions with an LLM payload.

    Usage:
        @trace_llm(model="gpt-4o")
        def call_my_model(prompt: str):
            return "completion text"
    """
    return _decorator_entry(arg, name, lambda f, n: _make_llm_decorator(f, n, model))


def _extract_llm_prompt(
    func: Callable[..., Any], args: tuple, kwargs: dict
) -> List[str]:
    bound = _bind_arguments(func, args, kwargs)
    for param in ("prompt", "prompts", "messages", "query", "input", "text"):
        if param in bound:
            val = bound[param]
            if isinstance(val, list):
                return [str(item) for item in val]
            return [str(val)]
    # Only fall back to the first positional argument: serializing arbitrary
    # keyword arguments could leak API keys or credentials into the payload.
    if args:
        return [str(args[0])]
    return [""]


def _extract_llm_completion(result: Any) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "content"):
        return str(result.content)
    if isinstance(result, dict) and "text" in result:
        return str(result["text"])
    return str(result)


def _make_llm_decorator(
    func: Callable[..., Any], name: str, model_override: Optional[str]
) -> Callable[..., Any]:
    model = model_override or "custom-llm"

    def start_payload(args: tuple, kwargs: dict) -> Dict[str, Any]:
        return {
            "model": model,
            "prompts": _extract_llm_prompt(func, args, kwargs),
            "completion": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "temperature": kwargs.get("temperature"),
            "streaming": False,
        }

    def end_payload(start: Dict[str, Any], result: Any) -> Dict[str, Any]:
        prompts = start.get("prompts") or []
        completion = _extract_llm_completion(result)
        prompt_tokens = estimate_tokens("\n".join(prompts), model)
        completion_tokens = estimate_tokens(completion, model)
        total_tokens = (
            None
            if prompt_tokens is None and completion_tokens is None
            else (prompt_tokens or 0) + (completion_tokens or 0)
        )
        return {
            **start,
            "completion": completion,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }

    def error_payload(start: Dict[str, Any], exc: BaseException) -> Dict[str, Any]:
        return {**start, "error": str(exc)}

    return _make_traced_decorator(
        func,
        name,
        agent_type="llm",
        event_prefix="llm",
        build_start_payload=start_payload,
        build_end_payload=end_payload,
        build_error_payload=error_payload,
    )


# --- Tool trace ---


def trace_tool(
    arg: Any = None,
    name: Optional[str] = None,
) -> Callable[..., Any]:
    """Decorator to instrument tool functions with a tool payload.

    Usage:
        @trace_tool(name="calculator")
        def calculate(expression: str):
            return eval_expression(expression)
    """
    return _decorator_entry(arg, name, _make_tool_decorator)


def _extract_tool_input(func: Callable[..., Any], args: tuple, kwargs: dict) -> str:
    bound = _bind_arguments(func, args, kwargs)
    for key in ("tool_input", "input", "query", "expression", "text"):
        if key in bound:
            return str(bound[key])
    if bound:
        return str(bound)
    if args:
        return str(args[0])
    if kwargs:
        return str(kwargs)
    return ""


def _make_tool_decorator(func: Callable[..., Any], name: str) -> Callable[..., Any]:
    description = inspect.getdoc(func)
    description = description.splitlines()[0] if description else None

    return _make_traced_decorator(
        func,
        name,
        agent_type="tool",
        event_prefix="tool",
        build_start_payload=lambda args, kwargs: {
            "tool_name": name,
            "tool_description": description,
            "input": _extract_tool_input(func, args, kwargs),
            "output": None,
            "error": None,
        },
        build_end_payload=lambda start, result: {**start, "output": str(result)},
        build_error_payload=lambda start, exc: {**start, "error": str(exc)},
    )


# --- Retriever trace ---


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
    return _decorator_entry(arg, name, _make_retriever_decorator)


def _extract_retriever_query(
    func: Callable[..., Any], args: tuple, kwargs: dict
) -> str:
    bound = _bind_arguments(func, args, kwargs)
    for key in ("query", "query_str", "prompt", "text", "search"):
        if key in bound:
            return str(bound[key])
    if args:
        return str(args[0])
    return ""


def _format_documents(result: Any) -> List[Dict[str, Any]]:
    """Normalize retriever results into ``{"content", "metadata"}`` documents."""
    items = result if isinstance(result, (list, tuple)) else [result]
    documents = []
    for doc in items:
        if isinstance(doc, dict):
            content = doc.get("content", doc.get("page_content", doc))
            metadata = doc.get("metadata") or {}
        else:
            content = getattr(doc, "page_content", None) or doc
            metadata = getattr(doc, "metadata", None) or {}
        documents.append({"content": str(content), "metadata": metadata})
    return documents


def _make_retriever_decorator(
    func: Callable[..., Any], name: str
) -> Callable[..., Any]:
    return _make_traced_decorator(
        func,
        name,
        agent_type="retriever",
        event_prefix="retriever",
        build_start_payload=lambda args, kwargs: {
            "query": _extract_retriever_query(func, args, kwargs),
            "documents": None,
        },
        build_end_payload=lambda start, result: {
            **start,
            "documents": _format_documents(result),
        },
        build_error_payload=lambda start, exc: {**start, "error": str(exc)},
    )
