import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from agentscope.exceptions import AgentScopeError
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


@pytest.fixture(autouse=True)
def _always_unpatch():
    yield
    unpatch_openai()


def _completion(text, prompt_tokens=10, completion_tokens=20):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


def _chunk(text, usage=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=SimpleNamespace(content=text))] if text else [],
        usage=usage,
    )


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self):
        self.closed = True


class _FakeAsyncStream:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._chunks)
        except StopIteration:
            raise StopAsyncIteration

    async def close(self):
        self.closed = True


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a minimal fake `openai` package exposing the patched classes."""
    chat_module = types.ModuleType("openai.resources.chat.completions")

    class Completions:
        result = None

        def create(self, *args, **kwargs):
            if isinstance(Completions.result, Exception):
                raise Completions.result
            return Completions.result

    class AsyncCompletions:
        result = None

        async def create(self, *args, **kwargs):
            return AsyncCompletions.result

    chat_module.Completions = Completions
    chat_module.AsyncCompletions = AsyncCompletions

    openai_module = types.ModuleType("openai")
    openai_module.__version__ = "9.9.9-test"
    monkeypatch.setitem(sys.modules, "openai", openai_module)
    monkeypatch.setitem(sys.modules, "openai.resources.chat.completions", chat_module)
    return chat_module


def test_patch_returns_false_when_openai_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", None)
    assert patch_openai() is False


def test_patch_fails_loudly_on_unexpected_layout(monkeypatch, fake_openai):
    del fake_openai.AsyncCompletions
    with pytest.raises(AgentScopeError, match="9.9.9-test"):
        patch_openai()


def test_unpatch_restores_sync_and_async(fake_openai):
    orig_sync = fake_openai.Completions.create
    orig_async = fake_openai.AsyncCompletions.create

    assert patch_openai() is True
    assert fake_openai.Completions.create is not orig_sync
    assert fake_openai.AsyncCompletions.create is not orig_async

    unpatch_openai()
    assert fake_openai.Completions.create is orig_sync
    assert fake_openai.AsyncCompletions.create is orig_async


def test_sync_call_emits_cost(fake_openai, mock_client):
    fake_openai.Completions.result = _completion("hi", 1000, 2000)
    patch_openai()

    res = fake_openai.Completions().create(
        model="gpt-4o", messages=[{"role": "user", "content": "hello"}]
    )

    assert res is fake_openai.Completions.result
    start, end = mock_client.events
    assert start["event_type"] == "llm_start"
    assert end["event_type"] == "llm_end"
    assert end["payload"]["completion"] == "hi"
    assert end["payload"]["total_tokens"] == 3000
    assert end["payload"]["cost_usd"] == pytest.approx(0.0225)


def test_sync_call_error_emits_llm_error(fake_openai, mock_client):
    fake_openai.Completions.result = RuntimeError("boom")
    patch_openai()

    with pytest.raises(RuntimeError, match="boom"):
        fake_openai.Completions().create(model="gpt-4o", messages=[])

    assert [e["event_type"] for e in mock_client.events] == ["llm_start", "llm_error"]
    assert mock_client.events[1]["payload"]["error"] == "boom"


def test_sync_stream_emits_llm_end_on_exhaustion(fake_openai, mock_client):
    usage = SimpleNamespace(prompt_tokens=5, completion_tokens=2, total_tokens=7)
    fake_openai.Completions.result = _FakeStream(
        [_chunk("Hel"), _chunk("lo"), _chunk(None, usage=usage)]
    )
    patch_openai()

    stream = fake_openai.Completions().create(model="gpt-4o", messages=[], stream=True)
    assert [e["event_type"] for e in mock_client.events] == ["llm_start"]

    chunks = list(stream)
    assert len(chunks) == 3
    end = mock_client.events[-1]
    assert end["event_type"] == "llm_end"
    assert end["payload"]["completion"] == "Hello"
    assert end["payload"]["total_tokens"] == 7
    assert end["payload"]["streaming"] is True

    stream.close()
    assert fake_openai.Completions.result.closed is True
    assert len(mock_client.events) == 2  # llm_end is emitted exactly once


def test_async_stream_emits_llm_end_on_exhaustion(fake_openai, mock_client):
    fake_openai.AsyncCompletions.result = _FakeAsyncStream([_chunk("a"), _chunk("b")])
    patch_openai()

    async def run():
        stream = await fake_openai.AsyncCompletions().create(
            model="gpt-4o", messages=[], stream=True
        )
        assert [e["event_type"] for e in mock_client.events] == ["llm_start"]
        return [chunk async for chunk in stream]

    chunks = asyncio.run(run())
    assert len(chunks) == 2
    assert mock_client.events[-1]["event_type"] == "llm_end"
    assert mock_client.events[-1]["payload"]["completion"] == "ab"
