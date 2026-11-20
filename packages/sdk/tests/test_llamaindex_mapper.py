"""LlamaIndexEventMapper unit tests with fake events (no LlamaIndex needed)."""

from types import SimpleNamespace

import pytest

from agentscope.integrations import llamaindex as li
from agentscope.integrations.llamaindex import LlamaIndexEventMapper, _BoundedDict


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def event(name, span_id, **fields):
    cls = type(name, (), {"class_name": classmethod(lambda c: name)})
    obj = cls()
    obj.span_id = span_id
    for k, v in fields.items():
        setattr(obj, k, v)
    return obj


@pytest.fixture
def mapper():
    return LlamaIndexEventMapper(Recorder())


def test_nested_llm_call_is_absorbed_and_contributes_usage(mapper):
    m = mapper
    m.on_span_enter("LLM.chat-1", None)
    m.on_event(
        event(
            "LLMChatStartEvent",
            "LLM.chat-1",
            messages=[],
            model_dict={"model": "gpt-4o"},
        )
    )
    m.on_span_enter("LLM.complete-2", "LLM.chat-1")
    m.on_event(
        event("LLMCompletionStartEvent", "LLM.complete-2", prompt="hi", model_dict={})
    )
    m.on_event(
        event(
            "LLMCompletionEndEvent",
            "LLM.complete-2",
            response=SimpleNamespace(
                text="x", additional_kwargs={"prompt_tokens": 3, "completion_tokens": 1}
            ),
        )
    )
    m.on_event(
        event(
            "LLMChatEndEvent",
            "LLM.chat-1",
            response=SimpleNamespace(
                message=SimpleNamespace(content="x"), additional_kwargs={}
            ),
        )
    )
    events = m.client.events
    assert [e["event_type"] for e in events] == ["llm_start", "llm_end"]
    assert events[1]["payload"]["total_tokens"] == 4
    assert events[1]["payload"]["cost_usd"] > 0


def test_end_without_start_and_unknown_events_are_ignored(mapper):
    mapper.on_event(event("QueryEndEvent", "Q.query-1", response="r"))
    mapper.on_event(event("EmbeddingStartEvent", "E-1"))
    mapper.on_event(object())
    assert mapper.client.events == []


def test_dropped_span_emits_error_for_open_node_only(mapper):
    mapper.on_span_enter("Q.query-1", None)
    mapper.on_event(event("QueryStartEvent", "Q.query-1", query="q"))
    mapper.on_span_drop("Q._query-2", RuntimeError("inner"))  # no node here
    mapper.on_span_drop("Q.query-1", RuntimeError("boom"))
    mapper.on_span_drop("Q.query-1", RuntimeError("again"))  # already closed
    types = [e["event_type"] for e in mapper.client.events]
    assert types == ["chain_start", "chain_error"]
    assert mapper.client.events[1]["payload"]["error"] == "boom"


def test_streaming_response_is_never_stringified():
    class StreamingResponse:
        response_gen = iter(["a", "b"])
        response_txt = None

        def __str__(self):  # str() would drain the user's stream
            raise AssertionError("str() must not be called on streaming responses")

    assert li._response_output(StreamingResponse()) == "[streaming response]"
    consumed = StreamingResponse()
    consumed.response_txt = "ab"
    assert li._response_output(consumed) == "ab"
    assert li._response_output(SimpleNamespace(response="plain")) == "plain"


def test_usage_extraction_variants():
    assert li._usage(
        SimpleNamespace(additional_kwargs={"prompt_tokens": 2, "completion_tokens": 3})
    ) == (2, 3, 5)
    raw = SimpleNamespace(usage=SimpleNamespace(input_tokens=4, output_tokens=1))
    assert li._usage(SimpleNamespace(additional_kwargs={}, raw=raw)) == (4, 1, 5)
    assert li._usage(SimpleNamespace(additional_kwargs={}, raw=None)) == (
        None,
        None,
        None,
    )


def test_model_name_resolution():
    assert li._model_name({"model": "gpt-4o"}, None) == "gpt-4o"
    assert (
        li._model_name({"model_name": "unknown", "class_name": "MockLLM"}, None)
        == "MockLLM"
    )
    assert li._model_name({}, "OpenAI.chat-123") == "OpenAI"


def test_bounded_dict_evicts_oldest():
    d = _BoundedDict(2)
    d["a"], d["b"], d["c"] = 1, 2, 3
    assert list(d) == ["b", "c"]


def test_emit_errors_are_swallowed():
    class Broken:
        def emit(self, e):
            raise RuntimeError("down")

    m = LlamaIndexEventMapper(Broken())
    m.on_span_enter("Q.query-1", None)
    m.on_event(event("QueryStartEvent", "Q.query-1", query="q"))


def test_events_follow_reconfigured_global_client(monkeypatch):
    import agentscope.decorators as decorators

    clients = []

    class FakeClient(Recorder):
        def __init__(self, session_name=None, **kwargs):
            super().__init__()
            self.session_name = session_name
            clients.append(self)

        def stop(self):
            pass

    monkeypatch.setattr(decorators, "AgentScopeClient", FakeClient)
    monkeypatch.setattr(decorators, "_global_client", None)

    decorators.configure(session_name="job-1")
    m = LlamaIndexEventMapper()
    m.on_span_enter("Q.query-1", None)
    m.on_event(event("QueryStartEvent", "Q.query-1", query="one"))
    decorators.configure(session_name="job-2")
    m.on_span_enter("Q.query-2", None)
    m.on_event(event("QueryStartEvent", "Q.query-2", query="two"))

    job1, job2 = clients
    assert [e["payload"]["inputs"]["query"] for e in job1.events] == ["one"]
    assert [e["payload"]["inputs"]["query"] for e in job2.events] == ["two"]


def test_node_without_end_event_closes_when_its_span_exits(mapper):
    mapper.on_span_enter("R.retrieve-1", None)
    mapper.on_event(
        event("RetrievalStartEvent", "R.retrieve-1", str_or_query_bundle="q")
    )
    mapper.on_span_exit("R.retrieve-1", result=[])
    assert [e["status"] for e in mapper.client.events] == ["running", "completed"]
    assert mapper._open == {}
