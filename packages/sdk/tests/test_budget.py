import uuid
from unittest.mock import MagicMock

import pytest
from langchain_core.outputs import Generation, LLMResult

from agentscope.callback import AgentScopeCallback
from agentscope.exceptions import BudgetExceededError


@pytest.mark.asyncio
async def test_budget_limit_exceeded():
    # Set a tiny budget limit of $0.0001
    callback = AgentScopeCallback(budget_limit_usd=0.0001)
    callback.client.emit = MagicMock()
    callback.client.patch_session_status = MagicMock()

    run_id = uuid.uuid4()

    # 1. Start LLM call
    await callback.on_llm_start(
        serialized={"name": "gpt-4o"},
        prompts=["User prompt"],
        run_id=run_id,
    )

    # 2. Complete LLM call with 10,000 output tokens for gpt-4o ($10/M tokens = $0.10)
    # This will exceed the $0.0001 budget
    response = LLMResult(
        generations=[[Generation(text="A long generated answer")]],
        llm_output={"token_usage": {"prompt_tokens": 100, "completion_tokens": 10000}},
    )

    with pytest.raises(BudgetExceededError) as exc_info:
        await callback.on_llm_end(response, run_id=run_id)

    assert "budget limit" in str(exc_info.value).lower()
    callback.client.patch_session_status.assert_called_once_with("failed")

    # 3. Subsequent LLM start should immediately raise BudgetExceededError
    next_run_id = uuid.uuid4()
    with pytest.raises(BudgetExceededError):
        await callback.on_llm_start(
            serialized={"name": "gpt-4o"},
            prompts=["Another prompt"],
            run_id=next_run_id,
        )


@pytest.mark.asyncio
async def test_budget_limit_within_bounds():
    # Set a generous budget limit of $5.00
    callback = AgentScopeCallback(budget_limit_usd=5.0)
    callback.client.emit = MagicMock()
    callback.client.patch_session_status = MagicMock()

    run_id = uuid.uuid4()
    await callback.on_llm_start(
        serialized={"name": "gpt-4o"},
        prompts=["Small prompt"],
        run_id=run_id,
    )

    response = LLMResult(
        generations=[[Generation(text="Short response")]],
        llm_output={"token_usage": {"prompt_tokens": 10, "completion_tokens": 10}},
    )

    # Should not raise
    await callback.on_llm_end(response, run_id=run_id)
    assert callback.cumulative_cost_usd > 0.0
    assert callback.cumulative_cost_usd < 5.0
    callback.client.patch_session_status.assert_not_called()
