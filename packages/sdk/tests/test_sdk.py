from unittest.mock import MagicMock

import pytest

from agentscope._pricing import calculate_cost
from agentscope.callback import AgentScopeCallback
from agentscope.decorators import get_global_client, trace


def test_calculate_cost():
    # gpt-4o price: 2.50 input / 10.00 output per 1M tokens
    assert calculate_cost("gpt-4o", 1_000_000, 1_000_000) == 12.50
    assert calculate_cost("unknown-model", 100, 100) == 0.0


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

