from unittest.mock import MagicMock

import pytest

from agentscope._pricing import calculate_cost
from agentscope.callback import AgentScopeCallback
from agentscope.decorators import get_global_client, trace


def test_calculate_cost():
    # gpt-4o price: 2.50 input / 10.00 output per 1M tokens
    assert calculate_cost("gpt-4o", 1_000_000, 1_000_000) == 12.50
    assert calculate_cost("unknown-model", 100, 100) == 0.0

    # New model pricing checks
    # claude-3-haiku: 0.25 input / 1.25 output per 1M tokens
    assert calculate_cost("claude-3-haiku", 1_000_000, 1_000_000) == 1.50
    # claude-3-opus: 15.00 input / 75.00 output per 1M tokens
    assert calculate_cost("claude-3-opus", 1_000_000, 1_000_000) == 90.00
    # gemini-1.5-flash: 0.075 input / 0.30 output per 1M tokens
    assert calculate_cost("gemini-1.5-flash", 1_000_000, 1_000_000) == pytest.approx(0.375)

    # Date-pinned & minor version matching
    assert calculate_cost("claude-3-haiku-20240307", 1_000_000, 1_000_000) == 1.50
    assert calculate_cost("CLAUDE-3-HAIKU-20240307", 1_000_000, 1_000_000) == 1.50
    assert calculate_cost("claude-3-opus-20240229", 1_000_000, 1_000_000) == 90.00
    assert calculate_cost("gemini-1.5-flash-001", 1_000_000, 1_000_000) == pytest.approx(0.375)
    assert calculate_cost("gpt-4o-2024-05-13", 1_000_000, 1_000_000) == 12.50

    # Ensure non-delimited model names do not false match
    assert calculate_cost("gpt-4orange", 1_000_000, 1_000_000) == 0.0
    assert calculate_cost("claude-3-haikuish", 1_000_000, 1_000_000) == 0.0

    # Negative token count validation
    with pytest.raises(ValueError, match="prompt_tokens cannot be negative"):
        calculate_cost("gpt-4o", -1, 100)
    with pytest.raises(ValueError, match="completion_tokens cannot be negative"):
        calculate_cost("gpt-4o", 100, -1)



@trace(name="test_sync")
def sync_fn(x):
    return x + 1


def test_decorators_sync():
    client = get_global_client()
    emitted = []
    client.emit = lambda event: emitted.append(event)

    res = sync_fn(5)
    assert res == 6
    assert len(emitted) == 2
    assert emitted[0]["event_type"] == "chain_start"
    assert emitted[0]["agent_name"] == "test_sync"
    assert emitted[1]["event_type"] == "chain_end"
    assert emitted[1]["payload"]["outputs"] == {"result": "6"}


@pytest.mark.asyncio
async def test_decorators_async():
    client = get_global_client()
    emitted = []
    client.emit = lambda event: emitted.append(event)

    @trace(name="test_async", agent_type="custom")
    async def async_fn(y):
        return y * 2

    res_async = await async_fn(10)
    assert res_async == 20
    assert len(emitted) == 2
    assert emitted[0]["event_type"] == "chain_start"
    assert emitted[0]["agent_name"] == "test_async"
    assert emitted[1]["event_type"] == "chain_end"
    assert emitted[1]["payload"]["outputs"] == {"result": "20"}


@pytest.mark.asyncio
async def test_callback_handler():
    callback = AgentScopeCallback()
    emitted = []
    callback.client.emit = lambda event: emitted.append(event)
    callback.client.patch_session_status = MagicMock()

    # Trigger start/end for chain
    import uuid

    run_id = uuid.uuid4()
    await callback.on_chain_start(
        serialized={"name": "test_chain"},
        inputs={"input_key": "val"},
        run_id=run_id,
    )
    assert len(emitted) == 1
    assert emitted[0]["event_type"] == "chain_start"
    assert emitted[0]["agent_name"] == "test_chain"
    assert emitted[0]["payload"]["inputs"] == {"input_key": "val"}

    await callback.on_chain_end(
        outputs={"output_key": "val_out"},
        run_id=run_id,
        parent_run_id=None,
    )
    assert len(emitted) == 2
    assert emitted[1]["event_type"] == "chain_end"
    assert emitted[1]["agent_name"] == "test_chain"
    assert emitted[1]["payload"]["chain_type"] == "test_chain"
    assert emitted[1]["payload"]["inputs"] == {"input_key": "val"}
    callback.client.patch_session_status.assert_called_once_with("completed")

    # Trigger error for chain
    error_run_id = uuid.uuid4()
    await callback.on_chain_start(
        serialized={"name": "error_chain"},
        inputs={"inp": "err"},
        run_id=error_run_id,
    )
    await callback.on_chain_error(
        error=ValueError("test error"),
        run_id=error_run_id,
        parent_run_id=None,
    )
    assert emitted[-1]["event_type"] == "chain_error"
    assert emitted[-1]["agent_name"] == "error_chain"
    assert emitted[-1]["payload"]["chain_type"] == "error_chain"
    assert emitted[-1]["payload"]["inputs"] == {"inp": "err"}
    assert emitted[-1]["payload"]["error"] == "test error"

    # Trigger LLM start/end/error
    llm_run_id = uuid.uuid4()
    await callback.on_llm_start(
        serialized={"name": "test_llm"},
        prompts=["hello"],
        run_id=llm_run_id,
        invocation_params={"model": "gpt-4o", "temperature": 0.7, "stream": True},
    )
    assert emitted[-1]["event_type"] == "llm_start"
    assert emitted[-1]["agent_name"] == "test_llm"
    assert emitted[-1]["payload"]["model"] == "gpt-4o"
    assert emitted[-1]["payload"]["prompts"] == ["hello"]
    assert emitted[-1]["payload"]["temperature"] == 0.7
    assert emitted[-1]["payload"]["streaming"] is True

    class DummyLLMResult:
        def __init__(self):
            self.generations = []
            self.llm_output = {
                "token_usage": {"prompt_tokens": 10, "completion_tokens": 20}
            }

    await callback.on_llm_end(
        response=DummyLLMResult(),
        run_id=llm_run_id,
    )
    assert emitted[-1]["event_type"] == "llm_end"
    assert emitted[-1]["agent_name"] == "test_llm"
    assert emitted[-1]["payload"]["model"] == "gpt-4o"
    assert emitted[-1]["payload"]["prompts"] == ["hello"]
    assert emitted[-1]["payload"]["temperature"] == 0.7
    assert emitted[-1]["payload"]["streaming"] is True

    # LLM error
    llm_error_run_id = uuid.uuid4()
    await callback.on_llm_start(
        serialized={"name": "err_llm"},
        prompts=["bad"],
        run_id=llm_error_run_id,
        invocation_params={"model": "gpt-4"},
    )
    await callback.on_llm_error(
        error=ValueError("llm crash"),
        run_id=llm_error_run_id,
    )
    assert emitted[-1]["event_type"] == "llm_error"
    assert emitted[-1]["agent_name"] == "err_llm"
    assert emitted[-1]["payload"]["model"] == "gpt-4"
    assert emitted[-1]["payload"]["prompts"] == ["bad"]

    # Trigger Tool start/end/error
    tool_run_id = uuid.uuid4()
    await callback.on_tool_start(
        serialized={"name": "test_tool", "description": "useful tool"},
        input_str="query_val",
        run_id=tool_run_id,
    )
    assert emitted[-1]["event_type"] == "tool_start"
    assert emitted[-1]["agent_name"] == "test_tool"
    assert emitted[-1]["payload"]["tool_name"] == "test_tool"
    assert emitted[-1]["payload"]["tool_description"] == "useful tool"
    assert emitted[-1]["payload"]["input"] == "query_val"

    await callback.on_tool_end(
        output="tool_result",
        run_id=tool_run_id,
    )
    assert emitted[-1]["event_type"] == "tool_end"
    assert emitted[-1]["agent_name"] == "test_tool"
    assert emitted[-1]["payload"]["tool_name"] == "test_tool"
    assert emitted[-1]["payload"]["tool_description"] == "useful tool"
    assert emitted[-1]["payload"]["input"] == "query_val"
    assert emitted[-1]["payload"]["output"] == "tool_result"

    # Trigger Retriever start/end
    ret_run_id = uuid.uuid4()
    await callback.on_retriever_start(
        serialized={"name": "test_retriever"},
        query="find docs",
        run_id=ret_run_id,
    )
    assert emitted[-1]["event_type"] == "retriever_start"
    assert emitted[-1]["agent_name"] == "test_retriever"
    assert emitted[-1]["payload"]["query"] == "find docs"

    class DummyDoc:
        def __init__(self, page_content, metadata):
            self.page_content = page_content
            self.metadata = metadata

    await callback.on_retriever_end(
        documents=[DummyDoc("found content", {"src": "web"})],
        run_id=ret_run_id,
    )
    assert emitted[-1]["event_type"] == "retriever_end"
    assert emitted[-1]["agent_name"] == "test_retriever"
    assert emitted[-1]["payload"]["query"] == "find docs"
    assert emitted[-1]["payload"]["documents"] == [
        {"content": "found content", "metadata": {"src": "web"}}
    ]


def test_client_pending_status_patch():
    from unittest.mock import MagicMock
    from agentscope.client import AgentScopeClient

    client = AgentScopeClient(host="localhost", port=8765, session_name="test_session")
    # session_id is initially None
    assert client.session_id is None
    assert client.pending_status is None

    # Call patch_session_status when session_id is not set yet
    client.patch_session_status("completed")

    # Verify that status is enqueued in pending_status
    assert client.pending_status == "completed"

    # Mock _send_status_patch
    client._send_status_patch = MagicMock()

    # Mock urllib.request.urlopen to simulate successful session creation
    import urllib.request
    from io import BytesIO

    mock_response = BytesIO(b'{"session_id": "test-uuid-123"}')
    original_urlopen = urllib.request.urlopen
    urllib.request.urlopen = MagicMock(return_value=mock_response)

    try:
        # Trigger creation
        client._create_session_sync()

        # Verify session_id is populated
        assert client.session_id == "test-uuid-123"
        # Verify pending_status was cleared
        assert client.pending_status is None
        # Verify _send_status_patch was called with enqueued status
        client._send_status_patch.assert_called_once_with(
            "test-uuid-123", "completed"
        )
    finally:
        urllib.request.urlopen = original_urlopen

