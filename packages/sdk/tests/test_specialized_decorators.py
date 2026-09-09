import pytest

from agentscope.decorators import trace_llm, trace_retriever, trace_tool


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
    assert start_event["payload"]["tool_input"] == "6 * 7"

    end_event = mock_client.events[1]
    assert end_event["event_type"] == "tool_end"
    assert end_event["payload"]["tool_output"] == "42"


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
    assert end_event["payload"]["documents"] == ["doc_alpha", "doc_beta"]


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
