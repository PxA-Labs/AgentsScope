"""LlamaIndex integration against real LlamaIndex (no network).

Uses LlamaIndex's MockEmbedding / MockLLM and an in-memory VectorStoreIndex.
Custom LLMs use LlamaIndex's own llm_completion_callback decorator, which is
how provider LLMs emit their instrumentation events.
"""

import asyncio
from typing import Any

import pytest

pytest.importorskip("llama_index.core")

from llama_index.core import Document, Settings, VectorStoreIndex  # noqa: E402
from llama_index.core.base.llms.types import (  # noqa: E402
    ChatMessage,
    CompletionResponse,
    CompletionResponseGen,
    LLMMetadata,
)
from llama_index.core.embeddings import MockEmbedding  # noqa: E402
from llama_index.core.llms import CustomLLM, MockLLM  # noqa: E402
from llama_index.core.llms.callbacks import llm_completion_callback  # noqa: E402

from agentscope._pricing import calculate_cost  # noqa: E402
from agentscope.decorators import trace  # noqa: E402
from agentscope.integrations.llamaindex import (  # noqa: E402
    instrument_llamaindex,
    uninstrument_llamaindex,
)


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class UsageLLM(CustomLLM):
    """Reports OpenAI-style usage in additional_kwargs, like llama-index-llms-openai."""

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name="gpt-4o")

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        return CompletionResponse(
            text="Paris.",
            additional_kwargs={"prompt_tokens": 40, "completion_tokens": 2},
        )

    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        yield CompletionResponse(text="Paris.", delta="Paris.")


class FailingLLM(UsageLLM):
    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any):
        raise RuntimeError("provider down")


DOCS = [
    Document(text="Paris is the capital of France.", metadata={"src": "a"}),
    Document(text="Berlin is the capital of Germany.", metadata={"src": "b"}),
]


@pytest.fixture
def rec():
    Settings.embed_model = MockEmbedding(embed_dim=8)
    Settings.llm = MockLLM(max_tokens=6)
    recorder = Recorder()
    instrument_llamaindex(agentscope_client=recorder)
    yield recorder
    uninstrument_llamaindex()


@pytest.fixture
def index(rec):
    idx = VectorStoreIndex.from_documents(DOCS)
    rec.events.clear()
    return idx


def nodes(rec):
    """Final (last) event per node id."""
    final = {}
    for e in rec.events:
        final[e["event_id"]] = e
    return final


def start_of(rec, node):
    return next(e for e in rec.events if e["event_id"] == node["event_id"])


def one(final, agent_type):
    matches = [n for n in final.values() if n["agent_type"] == agent_type]
    assert len(matches) == 1, (agent_type, matches)
    return matches[0]


def assert_rag_dag(rec):
    final = nodes(rec)
    query = one(final, "query")
    retriever = one(final, "retriever")
    synth = one(final, "synthesizer")
    llm = one(final, "llm")

    assert query["parent_event_id"] is None
    assert retriever["parent_event_id"] == query["event_id"]
    assert synth["parent_event_id"] == query["event_id"]
    assert llm["parent_event_id"] == synth["event_id"]
    assert all(n["status"] == "completed" for n in final.values())

    assert (
        start_of(rec, query)["payload"]["inputs"]["query"]
        == "What is the capital of France?"
    )
    assert retriever["agent_name"] == "VectorIndexRetriever"
    # MockEmbedding gives every text the same vector, so either document can
    # win; check that content and metadata belong together.
    (doc,) = retriever["payload"]["documents"]
    expected = {d.text: d.metadata["src"] for d in DOCS}
    assert doc["metadata"]["src"] == expected[doc["content"]]
    assert doc["metadata"]["score"] == pytest.approx(1.0)
    assert "node_id" in doc["metadata"]
    return final


def test_sync_query_engine_dag(index, rec):
    response = index.as_query_engine(similarity_top_k=1).query(
        "What is the capital of France?"
    )
    final = assert_rag_dag(rec)
    query = one(final, "query")
    assert query["payload"]["outputs"]["response"] == str(response)
    llm = one(final, "llm")
    assert llm["agent_name"] == "MockLLM"
    assert llm["payload"]["completion"] == str(response)


def test_async_query_engine_dag(index, rec):
    asyncio.run(
        index.as_query_engine(similarity_top_k=1).aquery(
            "What is the capital of France?"
        )
    )
    assert_rag_dag(rec)


def test_streaming_query_keeps_stream_intact_and_records_llm(index, rec):
    response = index.as_query_engine(similarity_top_k=1, streaming=True).query(
        "What is the capital of France?"
    )
    text = "".join(response.response_gen)
    # Regression: tracing must not consume the application's stream
    # (str(StreamingResponse) drains response_gen).
    assert text == "text text text text text text"

    final = nodes(rec)
    query, synth, llm = (one(final, t) for t in ("query", "synthesizer", "llm"))
    assert query["payload"]["outputs"]["response"] == "[streaming response]"
    assert synth["parent_event_id"] == query["event_id"]
    assert llm["status"] == "completed"
    # Completion is assembled from streamed deltas (what the app received).
    assert llm["payload"]["completion"] == text
    assert llm["payload"]["streaming"] is True
    # The LLM call runs while the stream is consumed, after the query's spans
    # have exited; LlamaIndex reports that span without a parent, so the node
    # is top-level (documented limitation).
    assert llm["parent_event_id"] is None


def test_streamed_llm_nests_under_enclosing_trace(index, rec, monkeypatch):
    monkeypatch.setattr("agentscope.decorators.get_global_client", lambda: rec)

    @trace(name="rag_request")
    def handle():
        response = index.as_query_engine(similarity_top_k=1, streaming=True).query(
            "What is the capital of France?"
        )
        return "".join(response.response_gen)

    assert handle() == "text text text text text text"
    outer_id = next(
        e["event_id"] for e in rec.events if e["agent_name"] == "rag_request"
    )
    final = nodes(rec)
    assert one(final, "query")["parent_event_id"] == outer_id
    assert one(final, "llm")["parent_event_id"] == outer_id


def test_usage_and_cost_from_reported_tokens(index, rec):
    Settings.llm = UsageLLM()
    index.as_query_engine(similarity_top_k=1).query("What is the capital of France?")
    llm = one(nodes(rec), "llm")
    payload = llm["payload"]
    assert llm["agent_name"] == "gpt-4o"
    assert (payload["prompt_tokens"], payload["completion_tokens"]) == (40, 2)
    assert payload["total_tokens"] == 42
    assert payload["cost_usd"] == pytest.approx(calculate_cost("gpt-4o", 40, 2))


def test_failure_marks_open_nodes_as_errors(index, rec):
    Settings.llm = FailingLLM()
    with pytest.raises(RuntimeError, match="provider down"):
        index.as_query_engine(similarity_top_k=1).query("What is the capital?")
    final = nodes(rec)
    assert one(final, "retriever")["status"] == "completed"
    for agent_type in ("llm", "synthesizer", "query"):
        node = one(final, agent_type)
        assert node["status"] == "error", agent_type
        assert node["payload"]["error"] == "provider down"
    assert one(final, "llm")["event_type"] == "llm_error"


def test_direct_chat_call_and_nesting_under_trace(rec, monkeypatch):
    # @trace emits through the global client; route it to the recorder too.
    monkeypatch.setattr("agentscope.decorators.get_global_client", lambda: rec)
    llm = MockLLM(max_tokens=3)
    llm.chat([ChatMessage(role="user", content="hi")])
    # MockLLM implements chat() via complete(): still exactly one LLM node.
    standalone = one(nodes(rec), "llm")
    assert standalone["parent_event_id"] is None
    assert standalone["payload"]["prompts"] == ["user: hi"]

    rec.events.clear()

    @trace(name="outer")
    def outer():
        return llm.chat([ChatMessage(role="user", content="again")])

    outer()
    nested = [e for e in rec.events if e["agent_type"] == "llm"][-1]
    outer_id = next(e["event_id"] for e in rec.events if e["agent_name"] == "outer")
    assert nested["parent_event_id"] == outer_id


def test_instrument_is_idempotent_and_uninstrument_stops_events(index, rec):
    assert instrument_llamaindex() is instrument_llamaindex()
    uninstrument_llamaindex()
    index.as_query_engine(similarity_top_k=1).query("anything")
    assert rec.events == []


class BrokenStreamLLM(UsageLLM):
    @llm_completion_callback()
    def stream_complete(
        self, prompt: str, formatted: bool = False, **kwargs: Any
    ) -> CompletionResponseGen:
        yield CompletionResponse(text="Par", delta="Par")
        raise RuntimeError("stream cut")


def streaming_query(index):
    return index.as_query_engine(similarity_top_k=1, streaming=True).query(
        "What is the capital of France?"
    )


def test_abandoned_stream_is_closed_not_left_running(rec):
    import gc

    mapper = instrument_llamaindex()
    stream = UsageLLM().stream_complete("hi")  # started, never consumed
    assert one(nodes(rec), "llm")["status"] == "running"
    del stream
    gc.collect()

    llm = one(nodes(rec), "llm")
    assert llm["event_type"] == "llm_end" and llm["status"] == "completed"
    assert llm["payload"]["closed_early"] is True
    assert mapper._open == {}


def test_partially_consumed_stream_is_closed_with_what_was_received(index, rec):
    import gc

    mapper = instrument_llamaindex()
    response = streaming_query(index)
    first = next(response.response_gen)
    del response
    gc.collect()

    llm = one(nodes(rec), "llm")
    assert llm["event_type"] == "llm_end" and llm["status"] == "completed"
    assert llm["payload"]["closed_early"] is True
    assert llm["payload"]["completion"].startswith(first)
    assert mapper._open == {}


def test_stream_failing_midway_marks_llm_error(index, rec):
    Settings.llm = BrokenStreamLLM()
    response = streaming_query(index)
    with pytest.raises(RuntimeError, match="stream cut"):
        "".join(response.response_gen)
    llm = one(nodes(rec), "llm")
    assert llm["event_type"] == "llm_error"
    assert llm["payload"]["error"] == "stream cut"


def test_instrumenting_again_with_a_client_switches_to_it(index, rec):
    other = Recorder()
    assert instrument_llamaindex(agentscope_client=other) is instrument_llamaindex()
    index.as_query_engine(similarity_top_k=1).query("anything")
    assert rec.events == [] and other.events
