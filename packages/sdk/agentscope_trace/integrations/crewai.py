"""CrewAI integration: stream crew, task, agent, tool and LLM events.

Usage::

    from agentscope.integrations.crewai import AgentScopeCrewAIListener

    listener = AgentScopeCrewAIListener(session_name="research-crew")
    crew.kickoff()

The listener subscribes to CrewAI's event bus (no monkey-patching) and maps
events onto AgentScope's model:

==========================================  ================================
CrewAI event                                AgentScope event
==========================================  ================================
crew kickoff started / completed / failed   chain_start / end / error (crew)
task started / completed / failed           chain_* (task)
agent execution started / completed / error chain_* (agent)
lite agent execution (``Agent.kickoff()``)  chain_* (agent)
tool usage started / finished / error       tool_start / end / error
LLM call started / completed / failed       llm_start / end / error
==========================================  ================================

CrewAI gives every event an ``event_id``, a ``parent_event_id`` and, for
completion events, the ``started_event_id`` they close. Start and end are sent
with the same AgentScope ``event_id`` (the server merges them). Internal
CrewAI events that are not shown (e.g. the agent executor's flow) are tracked
only to resolve each node's parent to its nearest *shown* ancestor, so the DAG
reads crew -> task -> agent -> tool / LLM.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from agentscope._pricing import calculate_cost
from agentscope.client import AgentScopeClient

logger = logging.getLogger(__name__)

_MAX_TEXT = 4000
# Safety cap on remembered open scopes (they are normally released when the
# scope's end event arrives).
_MAX_OPEN_SCOPES = 10_000

# CrewAI event ``type`` -> (AgentScope event_type, agent_type, phase)
_EVENT_MAP: Dict[str, Tuple[str, str, str]] = {
    "crew_kickoff_started": ("chain_start", "crew", "start"),
    "crew_kickoff_completed": ("chain_end", "crew", "end"),
    "crew_kickoff_failed": ("chain_error", "crew", "error"),
    "task_started": ("chain_start", "task", "start"),
    "task_completed": ("chain_end", "task", "end"),
    "task_failed": ("chain_error", "task", "error"),
    "agent_execution_started": ("chain_start", "agent", "start"),
    "agent_execution_completed": ("chain_end", "agent", "end"),
    "agent_execution_error": ("chain_error", "agent", "error"),
    # Standalone ``Agent.kickoff()`` (no crew) runs as a "lite agent".
    "lite_agent_execution_started": ("chain_start", "agent", "start"),
    "lite_agent_execution_completed": ("chain_end", "agent", "end"),
    "lite_agent_execution_error": ("chain_error", "agent", "error"),
    "tool_usage_started": ("tool_start", "tool", "start"),
    "tool_usage_finished": ("tool_end", "tool", "end"),
    "tool_usage_error": ("tool_error", "tool", "error"),
    "tool_execution_error": ("tool_error", "tool", "error"),
    "llm_call_started": ("llm_start", "llm", "start"),
    "llm_call_completed": ("llm_end", "llm", "end"),
    "llm_call_failed": ("llm_error", "llm", "error"),
}


def _truncate(value: Any, limit: int = _MAX_TEXT) -> str:
    text = value if isinstance(value, str) else _to_text(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    raw = getattr(value, "raw", None)  # CrewOutput / TaskOutput
    if isinstance(raw, str):
        return raw
    if isinstance(value, (dict, list)):
        try:
            return json.dumps(value, default=str, sort_keys=True)
        except (TypeError, ValueError):
            pass
    return str(value)


def _render_messages(messages: Any) -> List[str]:
    if messages is None:
        return []
    if isinstance(messages, str):
        return [_truncate(messages)]
    prompts = []
    for message in messages:
        if isinstance(message, dict):
            role = message.get("role", "user")
            prompts.append(_truncate(f"{role}: {message.get('content', '')}"))
        else:
            prompts.append(_truncate(str(message)))
    return prompts


def _usage(usage: Any) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    if not isinstance(usage, dict):
        return None, None, None
    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    total = usage.get("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return prompt, completion, total


def _iso(ts: Any) -> str:
    if isinstance(ts, datetime):
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.isoformat()
    return datetime.now(timezone.utc).isoformat()


def _task_name(event: Any) -> str:
    task = getattr(event, "task", None)
    name = getattr(event, "task_name", None) or getattr(task, "name", None)
    if not name:
        name = getattr(task, "description", None) or "Task"
    return _truncate(str(name), 80)


def _scope_starting_events() -> Optional[frozenset]:
    """CrewAI's scope-starting event types, or ``None`` without CrewAI."""
    try:
        from crewai.events.event_context import SCOPE_STARTING_EVENTS
    except Exception:
        return None
    return frozenset(SCOPE_STARTING_EVENTS)


def _event_classes() -> List[type]:
    """All concrete CrewAI event classes (imported lazily)."""
    import importlib
    import inspect
    import pkgutil

    import crewai.events.types as event_types
    from crewai.events.base_events import BaseEvent

    classes = []
    for info in pkgutil.iter_modules(event_types.__path__):
        try:
            module = importlib.import_module(f"{event_types.__name__}.{info.name}")
        except Exception:  # pragma: no cover - optional CrewAI submodules
            continue
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if (
                cls.__module__ == module.__name__
                and issubclass(cls, BaseEvent)
                and cls is not BaseEvent
            ):
                classes.append(cls)
    return classes


class CrewAIEventMapper:
    """Maps CrewAI events to AgentScope events (no CrewAI import needed).

    Kept separate from the bus subscription so the mapping can be tested and
    reused independently of how events are delivered.
    """

    def __init__(self, client: Any, mark_session_status: bool = True):
        self.client = client
        self.mark_session_status = mark_session_status
        self._lock = threading.Lock()
        # CrewAI sets an event's parent_event_id to the innermost open scope,
        # and only scope-starting events open scopes, so only those need
        # remembering; each is forgotten when its scope's end event (which
        # carries started_event_id) arrives. That keeps memory flat however
        # many kickoffs, events or streamed chunks a process sees.
        self._scope_types = _scope_starting_events()
        # open scope's event_id -> its parent_event_id.
        self._parents: Dict[str, Optional[str]] = {}
        # open scopes that produced an AgentScope node.
        self._shown: set = set()
        # start event id -> start timestamp, for latency.
        self._started_at: Dict[str, Any] = {}

    # -- event handling ---------------------------------------------------

    def handle(self, event: Any) -> None:
        """Process one CrewAI event (never raises)."""
        try:
            self._handle(event)
        except Exception as e:  # tracing must never break the crew
            logger.debug(f"AgentScope CrewAI listener ignored an event: {e}")

    def _resolve_parent(self, parent_id: Optional[str]) -> Optional[str]:
        seen = set()
        while parent_id and parent_id not in self._shown:
            if parent_id in seen:
                return None
            seen.add(parent_id)
            parent_id = self._parents.get(parent_id)
        return parent_id

    def _opens_scope(self, event_type: str) -> bool:
        if self._scope_types is not None:
            return event_type in self._scope_types
        return event_type.endswith("_started")  # without CrewAI (tests)

    def _remember_scope(self, event_id: str, parent_id: Optional[str]) -> None:
        self._parents[event_id] = parent_id
        while len(self._parents) > _MAX_OPEN_SCOPES:
            oldest = next(iter(self._parents))
            self._parents.pop(oldest)
            self._shown.discard(oldest)
            self._started_at.pop(oldest, None)

    def _forget_scope(self, started_id: Optional[str]) -> None:
        if started_id:
            self._parents.pop(started_id, None)
            self._shown.discard(started_id)
            self._started_at.pop(started_id, None)

    def _handle(self, event: Any) -> None:
        event_id = getattr(event, "event_id", None)
        if not event_id:
            return
        event_type = getattr(event, "type", "")
        if not isinstance(event_type, str):
            event_type = ""
        mapping = _EVENT_MAP.get(event_type)
        started_id = getattr(event, "started_event_id", None)
        parent_id = getattr(event, "parent_event_id", None)
        with self._lock:
            if self._opens_scope(event_type):
                self._remember_scope(event_id, parent_id)
            if mapping is None:
                self._forget_scope(started_id)
                return
            as_type, agent_type, phase = mapping
            node_id = event_id if phase == "start" else (started_id or event_id)
            parent = self._resolve_parent(parent_id)
            latency_ms = None
            if phase == "start":
                self._shown.add(event_id)
                self._started_at[event_id] = getattr(event, "timestamp", None)
            else:
                started = self._started_at.pop(node_id, None)
                ended = getattr(event, "timestamp", None)
                if isinstance(started, datetime) and isinstance(ended, datetime):
                    latency_ms = max(0, int((ended - started).total_seconds() * 1000))
            # The scope this event closes can no longer be anyone's parent.
            self._forget_scope(started_id)

        name, payload = self._describe(event, agent_type, phase)
        status = {"start": "running", "end": "completed", "error": "error"}[phase]
        self.client.emit(
            {
                "event_id": node_id,
                "session_id": "",
                "parent_event_id": parent,
                "event_type": as_type,
                "agent_name": name,
                "agent_type": agent_type,
                "timestamp": _iso(getattr(event, "timestamp", None)),
                "latency_ms": latency_ms,
                "status": status,
                "payload": payload,
            }
        )

        # Only the outermost crew decides the session's status: a crew kicked
        # off from inside another crew's tool or agent has a shown parent.
        if (
            agent_type == "crew"
            and phase != "start"
            and parent is None
            and self.mark_session_status
        ):
            self.client.patch_session_status(
                "completed" if phase == "end" else "failed"
            )

    def _describe(
        self, event: Any, agent_type: str, phase: str
    ) -> Tuple[str, Dict[str, Any]]:
        error = getattr(event, "error", None)
        error_text = None if error is None else _truncate(error)

        if agent_type == "llm":
            return self._describe_llm(event, phase, error_text)

        if agent_type == "tool":
            tool_name = str(getattr(event, "tool_name", None) or "tool")
            payload: Dict[str, Any] = {
                "tool_name": tool_name,
                "input": _truncate(getattr(event, "tool_args", "")),
                "output": None,
                "error": error_text,
            }
            if phase == "end":
                payload["output"] = _truncate(getattr(event, "output", ""))
                if getattr(event, "from_cache", False):
                    payload["from_cache"] = True
            return tool_name, payload

        if agent_type == "crew":
            name = str(getattr(event, "crew_name", None) or "Crew")
            inputs = getattr(event, "inputs", None) or {}
        elif agent_type == "task":
            name = _task_name(event)
            task = getattr(event, "task", None)
            inputs = {
                "description": _truncate(getattr(task, "description", "") or ""),
                "expected_output": _truncate(
                    getattr(task, "expected_output", "") or ""
                ),
            }
        else:  # agent
            agent = getattr(event, "agent", None)
            agent_info = getattr(event, "agent_info", None)
            if not isinstance(agent_info, dict):
                agent_info = {}
            name = str(
                getattr(event, "agent_role", None)
                or getattr(agent, "role", None)
                or agent_info.get("role")
                or "Agent"
            )
            if getattr(event, "type", "").startswith("lite_agent"):
                inputs = {
                    "messages": _render_messages(getattr(event, "messages", None))
                }
            else:
                inputs = {
                    "task_prompt": _truncate(getattr(event, "task_prompt", "") or "")
                }

        payload = {
            "chain_type": agent_type,
            "inputs": inputs if phase == "start" else {},
            "outputs": None,
            "error": error_text,
        }
        if phase == "end":
            outputs: Dict[str, Any] = {
                "output": _truncate(getattr(event, "output", ""))
            }
            total_tokens = getattr(event, "total_tokens", None)
            if total_tokens is not None:
                outputs["crew_total_tokens"] = total_tokens
            payload["outputs"] = outputs
        return name, payload

    def _describe_llm(
        self, event: Any, phase: str, error_text: Optional[str]
    ) -> Tuple[str, Dict[str, Any]]:
        model = str(getattr(event, "model", None) or "llm")
        payload: Dict[str, Any] = {
            "model": model,
            "prompts": _render_messages(getattr(event, "messages", None)),
            "completion": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "temperature": getattr(event, "temperature", None),
            "streaming": bool(getattr(event, "stream", False)),
        }
        if phase == "end":
            prompt, completion, total = _usage(getattr(event, "usage", None))
            payload.update(
                completion=_truncate(getattr(event, "response", "")),
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
            )
            if prompt is not None or completion is not None:
                try:
                    payload["cost_usd"] = calculate_cost(model, prompt, completion)
                except ValueError:
                    pass
        if phase == "error":
            payload["error"] = error_text
        return model, payload


class AgentScopeCrewAIListener:
    """Subscribe to CrewAI's event bus and stream events to AgentScope.

    Args:
        host / port: AgentScope server location.
        session_name / session_metadata: Session shown in the dashboard.
        client: Advanced/testing hook to supply an existing client.
        mark_session_status: Patch the session to ``completed`` / ``failed``
            when a top-level crew kickoff finishes (nested crews don't).
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        session_name: Optional[str] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
        client: Optional[AgentScopeClient] = None,
        mark_session_status: bool = True,
    ):
        try:
            from crewai.events import crewai_event_bus
        except ImportError as e:  # pragma: no cover - exercised without crewai
            raise ImportError(
                "AgentScopeCrewAIListener requires CrewAI. Install it with "
                "`pip install crewai` (or the agentscope-sdk[crewai] extra)."
            ) from e

        self.client = client or AgentScopeClient(
            host=host,
            port=port,
            session_name=session_name,
            session_metadata=session_metadata,
        )
        self.mapper = CrewAIEventMapper(self.client, mark_session_status)
        self._bus = crewai_event_bus
        self._registered: List[Tuple[type, Callable[..., Any]]] = []
        self._register()

    # -- registration -----------------------------------------------------

    def _register(self) -> None:
        # Async handlers run on the bus's event loop in emission order, so a
        # child is never processed before its parent (sync handlers run in a
        # thread pool with no ordering guarantee).
        mapper = self.mapper

        async def handler(source: Any, event: Any) -> None:
            mapper.handle(event)

        for cls in _event_classes():
            self._bus.on(cls)(handler)
            self._registered.append((cls, handler))

    def close(self, timeout: float = 10.0) -> None:
        """Deliver pending events, unsubscribe, and stop the AgentScope client.

        Waits (up to ``timeout`` seconds) for CrewAI to finish running queued
        handlers, so events emitted just before ``close()``, such as the
        final crew completion, are not lost.
        """
        try:
            self._bus.flush(timeout=timeout)
        except Exception:
            pass
        for cls, handler in self._registered:
            try:
                self._bus.off(cls, handler)
            except Exception:
                pass
        self._registered.clear()
        try:
            self.client.stop()
        except Exception:
            pass


def instrument_crewai(**kwargs: Any) -> AgentScopeCrewAIListener:
    """Create and register an :class:`AgentScopeCrewAIListener`."""
    return AgentScopeCrewAIListener(**kwargs)
