from agentscope._pricing import estimate_tokens


def test_estimate_tokens_with_text():
    prompt = "You are a helpful assistant assisting an agent."
    tokens = estimate_tokens(prompt, "gpt-4o")
    assert tokens is not None
    assert tokens > 0


def test_estimate_tokens_empty():
    assert estimate_tokens("") is None
    assert estimate_tokens(None) is None


def test_estimate_tokens_model_fallback():
    tokens = estimate_tokens("Hello world, this is a test prompt.", "unknown-model-xyz")
    assert tokens is not None
    assert tokens >= 1
