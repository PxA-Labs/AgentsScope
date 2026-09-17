import asyncio
import traceback

import pytest

from agentscope.decorators import trace, trace_llm, trace_retriever, trace_tool


class MockClient:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


@pytest.fixture(autouse=True)
def mock_client(monkeypatch):
    client = MockClient()
    monkeypatch.setattr("agentscope.decorators.get_global_client", lambda: client)
    return client


def test_trace_llm_sync(mock_client):
    @trace_llm(model="gpt-4o", name="custom_llm")
    def my_llm(prompt: str):
        return "Generated answer for " + prompt

    res = my_llm("Explain physics")
    assert res == "Generated answer for Explain physics"
    assert len(mock_client.events) == 2

    start_event = mock_client.events[0]
    assert start_event["event_type"] == "llm_start"
    assert start_event["agent_type"] == "llm"
    assert start_event["payload"]["model"] == "gpt-4o"
    assert "Explain physics" in start_event["payload"]["prompts"]

    end_event = mock_client.events[1]
    assert end_event["event_type"] == "llm_end"
    assert end_event["agent_type"] == "llm"
    assert end_event["payload"]["completion"] == "Generated answer for Explain physics"
    assert end_event["payload"]["prompt_tokens"] is not None


def test_trace_tool_sync(mock_client):
    @trace_tool(name="calculator")
    def calc(expression: str):
        return 42

    res = calc("6 * 7")
    assert res == 42
    assert len(mock_client.events) == 2

    start_event = mock_client.events[0]
    assert start_event["event_type"] == "tool_start"
    assert start_event["agent_type"] == "tool"
    assert start_event["payload"]["tool_name"] == "calculator"
    assert start_event["payload"]["input"] == "6 * 7"

    end_event = mock_client.events[1]
    assert end_event["event_type"] == "tool_end"
    assert end_event["payload"]["output"] == "42"


def test_trace_retriever_sync(mock_client):
    @trace_retriever(name="kb_search")
    def retrieve(query: str):
        return ["doc_alpha", "doc_beta"]

    res = retrieve("quantum")
    assert res == ["doc_alpha", "doc_beta"]
    assert len(mock_client.events) == 2

    start_event = mock_client.events[0]
    assert start_event["event_type"] == "retriever_start"
    assert start_event["agent_type"] == "retriever"
    assert start_event["payload"]["query"] == "quantum"

    end_event = mock_client.events[1]
    assert end_event["event_type"] == "retriever_end"
    assert end_event["payload"]["documents"] == [
        {"content": "doc_alpha", "metadata": {}},
        {"content": "doc_beta", "metadata": {}},
    ]


def test_trace_tool_error(mock_client):
    @trace_tool(name="failing_tool")
    def fail_tool():
        raise ValueError("Tool failure")

    with pytest.raises(ValueError, match="Tool failure"):
        fail_tool()

    assert len(mock_client.events) == 2
    err_event = mock_client.events[1]
    assert err_event["event_type"] == "tool_error"
    assert err_event["status"] == "error"
    assert "Tool failure" in err_event["payload"]["error"]


def test_trace_llm_does_not_serialize_keyword_arguments(mock_client):
    @trace_llm(model="gpt-4o")
    def call_model(**kwargs):
        return "ok"

    call_model(api_key="sk-secret-value", temperature=0.2)

    for event in mock_client.events:
        assert "sk-secret-value" not in str(event["payload"])


def test_trace_llm_async(mock_client):
    @trace_llm(model="gpt-4o")
    async def call_model(prompt: str):
        return "async answer"

    assert asyncio.run(call_model("hello")) == "async answer"
    assert [e["event_type"] for e in mock_client.events] == ["llm_start", "llm_end"]
    assert mock_client.events[1]["payload"]["completion"] == "async answer"
    assert mock_client.events[1]["latency_ms"] is not None


def test_trace_retriever_async_error(mock_client):
    @trace_retriever
    async def search(query: str):
        raise RuntimeError("index offline")

    with pytest.raises(RuntimeError, match="index offline"):
        asyncio.run(search("quantum"))

    err_event = mock_client.events[1]
    assert err_event["event_type"] == "retriever_error"
    assert err_event["agent_name"] == "search"
    assert err_event["payload"]["query"] == "quantum"
    assert err_event["payload"]["error"] == "index offline"


def test_errors_keep_original_traceback(mock_client):
    @trace_tool
    def broken():
        raise KeyError("missing")

    with pytest.raises(KeyError) as exc_info:
        broken()

    frames = [
        frame.name for frame in traceback.extract_tb(exc_info.value.__traceback__)
    ]
    assert frames[-1] == "broken"


def test_nested_decorators_link_parent_events(mock_client):
    @trace_tool(name="lookup")
    def lookup(query: str):
        return "result"

    @trace(name="pipeline")
    def pipeline():
        return lookup("x")

    pipeline()

    chain_start = mock_client.events[0]
    tool_start = mock_client.events[1]
    assert chain_start["event_type"] == "chain_start"
    assert tool_start["event_type"] == "tool_start"
    assert tool_start["parent_event_id"] == chain_start["event_id"]
