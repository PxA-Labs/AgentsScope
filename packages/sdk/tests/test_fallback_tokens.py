from unittest.mock import MagicMock

import pytest

from agentscope.callback import AgentScopeCallback
from agentscope.token_counter import estimate_tokens


def test_estimate_tokens_with_text():
    sample_text = "Hello world, this is a test prompt for local token estimation."
    count = estimate_tokens(sample_text, "gpt-4o")
    assert count > 0
    assert isinstance(count, int)


def test_estimate_tokens_empty():
    assert estimate_tokens("", "gpt-4o") == 0
    assert estimate_tokens(None, "gpt-4o") == 0


@pytest.mark.asyncio
async def test_on_llm_end_fallback_tokens_when_empty_usage():
    callback = AgentScopeCallback()
    callback.client = MagicMock()

    run_id = MagicMock()
    callback._run_metadata[run_id] = {
        "agent_name": "LocalAgent",
        "agent_type": "llm",
        "model": "ollama/llama3",
        "prompts": ["What is the capital of France?"],
        "temperature": 0.7,
        "streaming": False,
    }

    # Response with no llm_output or empty token_usage
    fake_generation = MagicMock()
    fake_generation.text = "The capital of France is Paris."
    fake_response = MagicMock()
    fake_response.generations = [[fake_generation]]
    fake_response.llm_output = {}

    await callback.on_llm_end(fake_response, run_id=run_id)

    assert callback.client.emit.called
    emitted_event = callback.client.emit.call_args[0][0]
    payload = emitted_event["payload"]

    assert payload["prompt_tokens"] is not None
    assert payload["prompt_tokens"] > 0
    assert payload["completion_tokens"] is not None
    assert payload["completion_tokens"] > 0
    assert (
        payload["total_tokens"]
        == payload["prompt_tokens"] + payload["completion_tokens"]
    )
