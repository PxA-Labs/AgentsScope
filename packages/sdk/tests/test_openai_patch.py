from unittest.mock import MagicMock

import pytest

from agentscope.patch import (
    _extract_completion,
    _extract_prompts,
    _extract_token_usage,
    patch_openai,
    unpatch_openai,
)


class MockClient:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


@pytest.fixture(autouse=True)
def mock_client(monkeypatch):
    client = MockClient()
    monkeypatch.setattr("agentscope.patch.get_global_client", lambda: client)
    return client


def test_extract_prompts():
    messages = [
        {"role": "system", "content": "Be concise"},
        {"role": "user", "content": "Hello!"},
    ]
    prompts = _extract_prompts(messages)
    assert prompts == ["system: Be concise", "user: Hello!"]


def test_extract_completion():
    mock_resp = MagicMock()
    choice = MagicMock()
    choice.message.content = "Quantum physics explanation"
    mock_resp.choices = [choice]

    comp = _extract_completion(mock_resp)
    assert comp == "Quantum physics explanation"


def test_extract_token_usage():
    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 10
    mock_resp.usage.completion_tokens = 25
    mock_resp.usage.total_tokens = 35

    p, c, t = _extract_token_usage(mock_resp)
    assert p == 10
    assert c == 25
    assert t == 35


def test_patch_unpatch_graceful():
    # Calling unpatch without error
    unpatch_openai()
    # patch returns bool (True or False depending on openai availability)
    res = patch_openai()
    assert isinstance(res, bool)
    unpatch_openai()
