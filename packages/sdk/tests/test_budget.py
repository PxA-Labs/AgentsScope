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


# --- Budget enforcement through a real LangChain run -------------------------
#
# The tests above call the handler methods directly. LangChain swallows and
# logs exceptions raised by callback handlers unless the handler sets
# ``raise_error = True``, so these tests drive an actual runnable to prove the
# budget really stops the run.


def _exceeded_callback():
    callback = AgentScopeCallback(budget_limit_usd=0.0001)
    callback.client.emit = MagicMock()
    callback.client.patch_session_status = MagicMock()
    callback.cumulative_cost_usd = 1.0  # already over the limit
    return callback


def test_exceeded_budget_stops_a_sync_langchain_run():
    from langchain_core.language_models import FakeListLLM

    llm = FakeListLLM(responses=["should not be returned"])
    with pytest.raises(BudgetExceededError):
        llm.invoke("hi", config={"callbacks": [_exceeded_callback()]})


@pytest.mark.asyncio
async def test_exceeded_budget_stops_an_async_langchain_run():
    from langchain_core.language_models import FakeListLLM

    llm = FakeListLLM(responses=["should not be returned"])
    with pytest.raises(BudgetExceededError):
        await llm.ainvoke("hi", config={"callbacks": [_exceeded_callback()]})


def test_budget_within_limit_does_not_interrupt_a_langchain_run():
    from langchain_core.language_models import FakeListLLM

    callback = AgentScopeCallback(budget_limit_usd=5.0)
    callback.client.emit = MagicMock()
    callback.client.patch_session_status = MagicMock()
    llm = FakeListLLM(responses=["ok"])
    assert llm.invoke("hi", config={"callbacks": [callback]}) == "ok"


def test_exceeded_budget_stops_a_sync_chat_model_run():
    from langchain_core.language_models import FakeListChatModel

    model = FakeListChatModel(responses=["should not be returned"])
    with pytest.raises(BudgetExceededError):
        model.invoke("hi", config={"callbacks": [_exceeded_callback()]})


@pytest.mark.asyncio
async def test_exceeded_budget_stops_an_async_chat_model_run():
    from langchain_core.language_models import FakeListChatModel

    model = FakeListChatModel(responses=["should not be returned"])
    with pytest.raises(BudgetExceededError):
        await model.ainvoke("hi", config={"callbacks": [_exceeded_callback()]})


def test_exceeded_budget_stops_a_sync_stream():
    from langchain_core.language_models import FakeListChatModel

    model = FakeListChatModel(responses=["should not be returned"])
    with pytest.raises(BudgetExceededError):
        list(model.stream("hi", config={"callbacks": [_exceeded_callback()]}))


def test_call_that_crosses_the_limit_blocks_the_next_call_in_a_sync_chain():
    """The crossing call completes; the run stops before the next model call."""
    from langchain_core.language_models import FakeListLLM
    from langchain_core.runnables import RunnableLambda

    callback = AgentScopeCallback(budget_limit_usd=0.0001)
    callback.client.emit = MagicMock()
    callback.client.patch_session_status = MagicMock()
    llm = FakeListLLM(responses=["first", "second"])
    completed = []

    def call_model(prompt):
        out = llm.invoke(prompt)
        completed.append(out)
        # Simulate the provider-reported cost of this call crossing the limit.
        callback.cumulative_cost_usd += 1.0
        return out

    chain = RunnableLambda(call_model) | RunnableLambda(call_model)
    with pytest.raises(BudgetExceededError):
        chain.invoke("start", config={"callbacks": [callback]})
    assert completed == ["first"]


def test_session_stays_failed_when_the_last_call_crosses_the_limit_in_a_sync_run():
    """A sync run can't be interrupted after its final model call, but the
    root chain ending must not overwrite the failed status with completed."""
    from langchain_core.language_models import FakeListLLM
    from langchain_core.runnables import RunnableLambda

    callback = AgentScopeCallback(budget_limit_usd=0.0001)
    callback.client.emit = MagicMock()
    callback.client.patch_session_status = MagicMock()
    llm = FakeListLLM(responses=["only"])

    def call_model(prompt):
        out = llm.invoke(prompt)
        callback.cumulative_cost_usd += 1.0  # this last call crosses the limit
        return out

    chain = RunnableLambda(lambda x: x) | RunnableLambda(call_model)
    assert chain.invoke("start", config={"callbacks": [callback]}) == "only"
    statuses = [c.args[0] for c in callback.client.patch_session_status.call_args_list]
    assert statuses and statuses[-1] == "failed", statuses
    assert "completed" not in statuses
