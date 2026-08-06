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
    callback.client.patch_session_status.assert_called_once_with("completed")
