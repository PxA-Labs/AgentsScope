"""LlamaIndex integration via ``llama_index.core.instrumentation``.

Usage::

    from agentscope.decorators import configure
    from agentscope.integrations.llamaindex import instrument_llamaindex

    configure(session_name="rag-app")
    instrument_llamaindex()
    index.as_query_engine().query("...")

A span handler and an event handler are added to LlamaIndex's root
dispatcher (the supported instrumentation API, not the legacy
CallbackManager). Shown as nodes:

==================================  ============================================
LlamaIndex events                   AgentScope
==================================  ============================================
QueryStart / QueryEnd               chain_start / chain_end (``query``)
RetrievalStart / RetrievalEnd       retriever_start / retriever_end (+ documents)
SynthesizeStart / SynthesizeEnd     chain_* (``synthesizer``)
ReRankStart / ReRankEnd             chain_* (``reranker``)
LLMChat* / LLMCompletion*           llm_start / llm_end (+ usage when reported)
==================================  ============================================

Start and end events of one operation share a span; LlamaIndex's span tree
is used to attach every node to its nearest shown ancestor. When an
operation raises, LlamaIndex drops its spans (no end events); any node open
in a dropped span is emitted as an error.
"""

import logging
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from agentscope._pricing import calculate_cost
from agentscope.decorators import current_parent_run_id, get_global_client

logger = logging.getLogger(__name__)

_MAX_TEXT = 4000
_MAX_DOC_TEXT = 1000
_MAX_DOCS = 20
# Span bookkeeping is bounded so long-running apps do not leak memory. It
# cannot simply be dropped on span exit: streamed LLM events arrive after
# their spans have exited.
_MAX_TRACKED_SPANS = 10_000

# class_name -> (kind, phase)
_EVENTS: Dict[str, Tuple[str, str]] = {
    "QueryStartEvent": ("query", "start"),
    "QueryEndEvent": ("query", "end"),
    "RetrievalStartEvent": ("retriever", "start"),
    "RetrievalEndEvent": ("retriever", "end"),
    "SynthesizeStartEvent": ("synthesizer", "start"),
    "SynthesizeEndEvent": ("synthesizer", "end"),
    "ReRankStartEvent": ("reranker", "start"),
    "ReRankEndEvent": ("reranker", "end"),
    "LLMChatStartEvent": ("llm", "start"),
    "LLMChatEndEvent": ("llm", "end"),
    "LLMCompletionStartEvent": ("llm", "start"),
    "LLMCompletionEndEvent": ("llm", "end"),
}

_EVENT_TYPES = {
    "query": ("chain_start", "chain_end", "chain_error"),
    "synthesizer": ("chain_start", "chain_end", "chain_error"),
    "reranker": ("chain_start", "chain_end", "chain_error"),
    "retriever": ("retriever_start", "retriever_end", "chain_error"),
    "llm": ("llm_start", "llm_end", "llm_error"),
}


def _truncate(value: Any, limit: int = _MAX_TEXT) -> str:
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _query_text(query: Any) -> str:
    if query is None:
        return ""
    return _truncate(getattr(query, "query_str", None) or str(query))


def _response_output(response: Any) -> str:
    """Text of a query/synthesis response without consuming streams.

    str() on a StreamingResponse drains its response_gen to build the text,
    which would leave nothing for the application to read. Streaming
    responses are therefore never stringified.
    """
    if response is None:
        return ""
    if hasattr(response, "response_gen") or hasattr(response, "async_response_gen"):
        consumed = getattr(response, "response_txt", None)
        return _truncate(consumed) if consumed else "[streaming response]"
    text = getattr(response, "response", None)
    if isinstance(text, str):
        return _truncate(text)
    return _truncate(str(response))


def _span_owner(span_id: Optional[str]) -> str:
    # LlamaIndex span ids look like "VectorIndexRetriever.retrieve-<uuid>".
    if not span_id:
        return ""
    return span_id.split(".", 1)[0]


def _field(obj: Any, name: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _usage(response: Any) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """Token usage from a ChatResponse / CompletionResponse, if reported."""
    for source in (
        _field(response, "additional_kwargs"),
        _field(_field(response, "raw"), "usage"),
    ):
        if not source:
            continue
        prompt = _field(source, "prompt_tokens")
        if prompt is None:
            prompt = _field(source, "input_tokens")
        completion = _field(source, "completion_tokens")
        if completion is None:
            completion = _field(source, "output_tokens")
        if prompt is None and completion is None:
            continue
        total = _field(source, "total_tokens")
        if total is None and prompt is not None and completion is not None:
            total = prompt + completion
        return prompt, completion, total
    return None, None, None


def _model_name(model_dict: Any, span_id: Optional[str]) -> str:
    if isinstance(model_dict, dict):
        for key in ("model", "model_name"):
            value = model_dict.get(key)
            if value and value != "unknown":
                return str(value)
        if model_dict.get("class_name"):
            return str(model_dict["class_name"])
    return _span_owner(span_id) or "llm"


def _render_messages(messages: Any) -> List[str]:
    prompts = []
    for message in messages or []:
        role = _field(message, "role")
        role = getattr(role, "value", role) or "user"
        prompts.append(_truncate(f"{role}: {_field(message, 'content') or ''}"))
    return prompts


def _response_text(response: Any) -> str:
    message = _field(response, "message")
    if message is not None:
        return _truncate(_field(message, "content") or "")
    text = _field(response, "text")
    if text is not None:
        return _truncate(text)
    return _truncate(response if response is not None else "")


def _documents(nodes: Any) -> List[Dict[str, Any]]:
    docs = []
    for scored in list(nodes or [])[:_MAX_DOCS]:
        node = getattr(scored, "node", scored)
        try:
            content = node.get_content()
        except Exception:
            content = str(getattr(node, "text", ""))
        metadata = dict(getattr(node, "metadata", None) or {})
        score = getattr(scored, "score", None)
        if score is not None:
            metadata["score"] = score
        node_id = getattr(node, "node_id", None) or getattr(node, "id_", None)
        if node_id:
            metadata["node_id"] = node_id
        docs.append(
            {"content": _truncate(content, _MAX_DOC_TEXT), "metadata": metadata}
        )
    return docs


class _BoundedDict(OrderedDict):
    def __init__(self, maxsize: int):
        super().__init__()
        self.maxsize = maxsize

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        while len(self) > self.maxsize:
            self.popitem(last=False)


class LlamaIndexEventMapper:
    """Maps LlamaIndex spans and events to AgentScope events.

    Independent of LlamaIndex classes (uses ``class_name()`` strings), so it
    can be tested and driven without LlamaIndex installed.
    """

    def __init__(self, client: Any = None):
        self._client = client
        self._lock = threading.Lock()
        # span id -> AgentScope node id of its nearest shown ancestor span
        self._anchor: _BoundedDict = _BoundedDict(_MAX_TRACKED_SPANS)
        # span id -> node id of the node opened in that span
        self._span_node: _BoundedDict = _BoundedDict(_MAX_TRACKED_SPANS)
        # node id -> open node state
        self._open: Dict[str, Dict[str, Any]] = {}
        # span id -> outer LLM node id, for LLM calls implemented on top of
        # another LLM call (e.g. chat() via complete()); shown as one node.
        self._absorbed: _BoundedDict = _BoundedDict(_MAX_TRACKED_SPANS)

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                self._client = get_global_client()
            except Exception:
                return None
        return self._client

    # -- spans ------------------------------------------------------------

    def on_span_enter(self, span_id: str, parent_span_id: Optional[str]) -> None:
        with self._lock:
            if parent_span_id is None:
                # Root span: attach to the surrounding @trace context, if any.
                anchor = current_parent_run_id.get()
            else:
                anchor = self._span_node.get(parent_span_id) or self._anchor.get(
                    parent_span_id
                )
            self._anchor[span_id] = anchor

    def on_span_drop(self, span_id: str, err: Optional[BaseException]) -> None:
        with self._lock:
            node_id = self._span_node.get(span_id)
            node = self._open.pop(node_id, None) if node_id else None
        if node is not None:
            self._emit_error(node, err)

    # -- events -----------------------------------------------------------

    def on_event(self, event: Any) -> None:
        try:
            self._on_event(event)
        except Exception as e:  # tracing must never break the app
            logger.debug(f"AgentScope LlamaIndex mapper ignored an event: {e}")

    def _on_event(self, event: Any) -> None:
        name = type(event).__name__
        try:
            name = event.class_name()
        except Exception:
            pass
        if name in ("LLMChatInProgressEvent", "LLMCompletionInProgressEvent"):
            self._stream_delta(getattr(event, "span_id", None), event)
            return
        mapping = _EVENTS.get(name)
        if mapping is None:
            return
        kind, phase = mapping
        span_id = getattr(event, "span_id", None)
        if phase == "start":
            self._start(kind, span_id, event)
        else:
            self._end(kind, span_id, event)

    def _start(self, kind: str, span_id: Optional[str], event: Any) -> None:
        node_id = str(uuid.uuid4())
        with self._lock:
            parent = self._anchor.get(span_id) if span_id else None
            outer = self._open.get(parent) if parent else None
            if kind == "llm" and outer is not None and outer["kind"] == "llm":
                if span_id:
                    self._absorbed[span_id] = parent
                return
            if span_id:
                self._span_node[span_id] = node_id
        name, payload = self._describe_start(kind, span_id, event)
        node = {
            "id": node_id,
            "kind": kind,
            "name": name,
            "parent": parent,
            "t0": time.perf_counter(),
            "start_payload": payload,
        }
        with self._lock:
            self._open[node_id] = node
        self._emit(node, 0, "running", payload, latency_ms=None)

    def _stream_delta(self, span_id: Optional[str], event: Any) -> None:
        """Accumulate streamed deltas: exactly what the application receives."""
        delta = _field(getattr(event, "response", None), "delta")
        if not span_id or not isinstance(delta, str):
            return
        with self._lock:
            node_id = self._span_node.get(span_id) or self._absorbed.get(span_id)
            node = self._open.get(node_id) if node_id else None
            if node is not None and node["kind"] == "llm":
                node.setdefault("stream_parts", []).append(delta)

    def _end(self, kind: str, span_id: Optional[str], event: Any) -> None:
        with self._lock:
            outer_id = self._absorbed.pop(span_id, None) if span_id else None
            if outer_id is not None:
                outer = self._open.get(outer_id)
                usage = _usage(getattr(event, "response", None))
                if outer is not None and any(v is not None for v in usage):
                    outer["inner_usage"] = usage
                return
            node_id = self._span_node.get(span_id) if span_id else None
            node = self._open.pop(node_id, None) if node_id else None
        if node is None or node["kind"] != kind:
            return
        payload = self._describe_end(kind, node, event)
        self._emit(node, 1, "completed", payload, self._latency(node))

    def _emit_error(self, node: Dict[str, Any], err: Optional[BaseException]) -> None:
        payload = dict(node["start_payload"])
        payload["error"] = str(err) if err is not None else "operation failed"
        if node["kind"] in ("query", "synthesizer", "reranker", "retriever"):
            payload = {
                "chain_type": node["kind"],
                "inputs": {},
                "outputs": None,
                "error": payload["error"],
            }
        self._emit(node, 2, "error", payload, self._latency(node))

    # -- payloads ---------------------------------------------------------

    def _describe_start(
        self, kind: str, span_id: Optional[str], event: Any
    ) -> Tuple[str, Dict[str, Any]]:
        if kind == "llm":
            model_dict = getattr(event, "model_dict", None) or {}
            prompt = getattr(event, "prompt", None)
            prompts = (
                [_truncate(prompt)]
                if prompt is not None
                else _render_messages(getattr(event, "messages", None))
            )
            model = _model_name(model_dict, span_id)
            return model, {
                "model": model,
                "prompts": prompts,
                "completion": None,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
                "temperature": (
                    model_dict.get("temperature")
                    if isinstance(model_dict, dict)
                    else None
                ),
                "streaming": False,
            }
        if kind == "retriever":
            return _span_owner(span_id) or "retriever", {
                "query": _query_text(getattr(event, "str_or_query_bundle", None)),
                "documents": None,
            }
        if kind == "reranker":
            name = (
                getattr(event, "model_name", None) or _span_owner(span_id) or "rerank"
            )
            inputs = {
                "query": _query_text(getattr(event, "query", None)),
                "top_n": getattr(event, "top_n", None),
                "candidates": len(getattr(event, "nodes", None) or []),
            }
        else:
            name = "query" if kind == "query" else "synthesize"
            inputs = {"query": _query_text(getattr(event, "query", None))}
        return str(name), {
            "chain_type": kind,
            "inputs": inputs,
            "outputs": None,
            "error": None,
        }

    def _describe_end(
        self, kind: str, node: Dict[str, Any], event: Any
    ) -> Dict[str, Any]:
        if kind == "llm":
            response = getattr(event, "response", None)
            prompt, completion, total = _usage(response)
            if prompt is None and completion is None and node.get("inner_usage"):
                prompt, completion, total = node["inner_usage"]
            payload = dict(node["start_payload"])
            parts = node.get("stream_parts")
            if parts:
                payload["streaming"] = True
            payload.update(
                completion=(
                    _truncate("".join(parts)) if parts else _response_text(response)
                ),
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=total,
            )
            if prompt is not None or completion is not None:
                try:
                    payload["cost_usd"] = calculate_cost(
                        payload["model"], prompt, completion
                    )
                except ValueError:
                    pass
            return payload
        if kind == "retriever":
            return {
                **node["start_payload"],
                "documents": _documents(getattr(event, "nodes", None)),
            }
        if kind == "reranker":
            outputs: Dict[str, Any] = {
                "documents": _documents(getattr(event, "nodes", None))
            }
        else:
            outputs = {"response": _response_output(getattr(event, "response", None))}
        return {
            "chain_type": kind,
            "inputs": {},
            "outputs": outputs,
            "error": None,
        }

    # -- emit -------------------------------------------------------------

    @staticmethod
    def _latency(node: Dict[str, Any]) -> int:
        return int((time.perf_counter() - node["t0"]) * 1000)

    def _emit(
        self,
        node: Dict[str, Any],
        phase_index: int,
        status: str,
        payload: Dict[str, Any],
        latency_ms: Optional[int],
    ) -> None:
        client = self.client
        if client is None:
            return
        kind = node["kind"]
        try:
            client.emit(
                {
                    "event_id": node["id"],
                    "session_id": "",
                    "parent_event_id": node["parent"],
                    "event_type": _EVENT_TYPES[kind][phase_index],
                    "agent_name": node["name"],
                    "agent_type": (
                        "retriever"
                        if kind == "retriever"
                        else ("llm" if kind == "llm" else kind)
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "latency_ms": latency_ms,
                    "status": status,
                    "payload": payload,
                }
            )
        except Exception as e:
            logger.debug(f"AgentScope LlamaIndex emit failed: {e}")


# --------------------------------------------------------------------------
# LlamaIndex handler wiring
# --------------------------------------------------------------------------

_installed: Optional[Tuple[Any, Any, Any, LlamaIndexEventMapper]] = None
_install_lock = threading.Lock()


def instrument_llamaindex(agentscope_client: Any = None) -> LlamaIndexEventMapper:
    """Add AgentScope span and event handlers to LlamaIndex's root dispatcher.

    Idempotent: calling it again returns the existing mapper.

    Args:
        agentscope_client: Override the AgentScope client (defaults to the
            global client from ``agentscope.decorators.configure``).
    """
    global _installed
    with _install_lock:
        if _installed is not None:
            return _installed[3]

        from llama_index.core.instrumentation import get_dispatcher
        from llama_index.core.instrumentation.event_handlers import BaseEventHandler
        from llama_index.core.instrumentation.span import SimpleSpan
        from llama_index.core.instrumentation.span_handlers import BaseSpanHandler
        from pydantic import PrivateAttr

        mapper = LlamaIndexEventMapper(agentscope_client)

        class AgentScopeSpanHandler(BaseSpanHandler[SimpleSpan]):
            _mapper: Any = PrivateAttr()

            @classmethod
            def class_name(cls) -> str:
                return "AgentScopeSpanHandler"

            def new_span(
                self,
                id_: str,
                bound_args: Any,
                instance: Any = None,
                parent_span_id: Optional[str] = None,
                tags: Optional[Dict[str, Any]] = None,
                **kwargs: Any,
            ) -> SimpleSpan:
                self._mapper.on_span_enter(id_, parent_span_id)
                return SimpleSpan(id_=id_, parent_id=parent_span_id, tags=tags or {})

            def prepare_to_exit_span(
                self,
                id_: str,
                bound_args: Any,
                instance: Any = None,
                result: Any = None,
                **kwargs: Any,
            ) -> Optional[SimpleSpan]:
                with self.lock:
                    return self.open_spans.get(id_)

            def prepare_to_drop_span(
                self,
                id_: str,
                bound_args: Any,
                instance: Any = None,
                err: Any = None,
                **kwargs: Any,
            ) -> Optional[SimpleSpan]:
                self._mapper.on_span_drop(id_, err)
                with self.lock:
                    return self.open_spans.get(id_)

        class AgentScopeEventHandler(BaseEventHandler):
            _mapper: Any = PrivateAttr()

            @classmethod
            def class_name(cls) -> str:
                return "AgentScopeEventHandler"

            def handle(self, event: Any, **kwargs: Any) -> Any:
                self._mapper.on_event(event)

        span_handler = AgentScopeSpanHandler()
        span_handler._mapper = mapper
        event_handler = AgentScopeEventHandler()
        event_handler._mapper = mapper

        dispatcher = get_dispatcher()
        dispatcher.add_span_handler(span_handler)
        dispatcher.add_event_handler(event_handler)
        _installed = (dispatcher, span_handler, event_handler, mapper)
        return mapper


def uninstrument_llamaindex() -> None:
    """Remove the handlers added by :func:`instrument_llamaindex`."""
    global _installed
    with _install_lock:
        if _installed is None:
            return
        dispatcher, span_handler, event_handler, _ = _installed
        for handlers, handler in (
            (dispatcher.span_handlers, span_handler),
            (dispatcher.event_handlers, event_handler),
        ):
            try:
                handlers.remove(handler)
            except ValueError:
                pass
        _installed = None
