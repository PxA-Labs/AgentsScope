"""patch_anthropic against the real Anthropic SDK with a mocked HTTP transport.

No network: httpx.MockTransport serves canned Messages API responses, so the
SDK's own request building, response parsing and SSE decoding are exercised.
"""

import asyncio
import json
import sys

import pytest

anthropic = pytest.importorskip("anthropic")

# Recent Anthropic SDKs are built on the httpx2 fork and reject plain httpx
# clients; older ones use httpx. Mock with whichever the SDK depends on.
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover - depends on installed SDK version
    httpx = pytest.importorskip("httpx")

from anthropic.resources.messages import AsyncMessages, Messages  # noqa: E402

from agentscope import trace  # noqa: E402
from agentscope.exceptions import AgentScopeError  # noqa: E402
from agentscope.providers import anthropic as provider  # noqa: E402
from agentscope.providers.anthropic import (  # noqa: E402
    patch_anthropic,
    unpatch_anthropic,
)

MODEL = "claude-3-5-sonnet-20241022"

MESSAGE = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": MODEL,
    "content": [
        {"type": "text", "text": "Paris."},
        {"type": "tool_use", "id": "tu_1", "name": "lookup", "input": {"q": "fr"}},
    ],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 12,
        "output_tokens": 5,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 0,
    },
}

SSE_EVENTS = [
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                **MESSAGE,
                "content": [],
                "stop_reason": None,
                "usage": {
                    "input_tokens": 12,
                    "output_tokens": 1,
                    "cache_read_input_tokens": 3,
                },
            },
        },
    ),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Par"},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "is."},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 5},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
]


def sse_body() -> bytes:
    return "".join(
        f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in SSE_EVENTS
    ).encode()


def handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if body.get("model") == "fail":
        return httpx.Response(
            400,
            json={
                "type": "error",
                "error": {"type": "invalid_request_error", "message": "bad model"},
            },
        )
    if body.get("stream"):
        return httpx.Response(
            200, content=sse_body(), headers={"content-type": "text/event-stream"}
        )
    return httpx.Response(200, json=MESSAGE)


def sync_client():
    return anthropic.Anthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def async_client():
    return anthropic.AsyncAnthropic(
        api_key="test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


@pytest.fixture(autouse=True)
def recorder(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(provider, "get_global_client", lambda: rec)
    monkeypatch.setattr("agentscope.decorators.get_global_client", lambda: rec)
    yield rec
    unpatch_anthropic()


def llm_events(rec):
    return [e for e in rec.events if e["agent_type"] == "llm"]


def assert_completed(events, completion, streaming):
    start, end = events
    assert start["event_type"] == "llm_start"
    assert end["event_type"] == "llm_end"
    assert start["event_id"] == end["event_id"]
    assert end["agent_name"] == f"Anthropic:{MODEL}"
    payload = end["payload"]
    assert payload["model"] == MODEL
    assert payload["prompts"] == ["system: Be brief", "user: Capital of France?"]
    assert payload["streaming"] is streaming
    assert payload["completion"] == completion
    assert payload["prompt_tokens"] == 12
    assert payload["completion_tokens"] == 5
    assert payload["total_tokens"] == 17
    assert payload["cost_usd"] > 0
    assert payload["usage_details"]["cache_read_input_tokens"] == 3
    assert end["latency_ms"] is not None


REQUEST = dict(
    model=MODEL,
    max_tokens=64,
    system="Be brief",
    messages=[{"role": "user", "content": "Capital of France?"}],
)


def test_sync_create(recorder):
    assert patch_anthropic() is True
    res = sync_client().messages.create(**REQUEST)
    assert res.content[0].text == "Paris."
    assert_completed(
        llm_events(recorder),
        'Paris.[tool_use lookup: {"q": "fr"}]',
        streaming=False,
    )


def test_async_create(recorder):
    patch_anthropic()

    async def run():
        return await async_client().messages.create(**REQUEST)

    res = asyncio.run(run())
    assert res.usage.output_tokens == 5
    assert_completed(
        llm_events(recorder), 'Paris.[tool_use lookup: {"q": "fr"}]', False
    )


def test_sync_create_stream_true(recorder):
    patch_anthropic()
    stream = sync_client().messages.create(**REQUEST, stream=True)
    types = [event.type for event in stream]
    assert types[0] == "message_start" and types[-1] == "message_stop"
    assert_completed(llm_events(recorder), "Paris.", streaming=True)


def test_async_create_stream_true(recorder):
    patch_anthropic()

    async def run():
        stream = await async_client().messages.create(**REQUEST, stream=True)
        return [event.type async for event in stream]

    types = asyncio.run(run())
    assert "content_block_delta" in types
    assert_completed(llm_events(recorder), "Paris.", streaming=True)


def test_sync_stream_helper(recorder):
    patch_anthropic()
    with sync_client().messages.stream(**REQUEST) as stream:
        text = "".join(stream.text_stream)
    assert text == "Paris."
    assert_completed(llm_events(recorder), "Paris.", streaming=True)


def test_async_stream_helper(recorder):
    patch_anthropic()

    async def run():
        async with async_client().messages.stream(**REQUEST) as stream:
            return "".join([t async for t in stream.text_stream])

    assert asyncio.run(run()) == "Paris."
    assert_completed(llm_events(recorder), "Paris.", streaming=True)


def test_stream_helper_user_exception_after_completion_records_llm_end(recorder):
    # The API call succeeded; an exception from the caller's own code inside
    # the with block is not an LLM error and must not drop the usage.
    patch_anthropic()
    with pytest.raises(ValueError, match="caller bug"):
        with sync_client().messages.stream(**REQUEST) as stream:
            stream.get_final_message()
            raise ValueError("caller bug")
    assert_completed(llm_events(recorder), "Paris.", streaming=True)


def test_async_stream_helper_user_exception_after_completion_records_llm_end(
    recorder,
):
    patch_anthropic()

    async def run():
        async with async_client().messages.stream(**REQUEST) as stream:
            await stream.get_final_message()
            raise ValueError("caller bug")

    with pytest.raises(ValueError, match="caller bug"):
        asyncio.run(run())
    assert_completed(llm_events(recorder), "Paris.", streaming=True)


def test_stream_helper_exception_before_message_completes_records_llm_error(
    recorder,
):
    patch_anthropic()
    with pytest.raises(ValueError, match="mid-stream"):
        with sync_client().messages.stream(**REQUEST) as stream:
            next(iter(stream))  # message_start only; no final message yet
            raise ValueError("mid-stream")
    start, err = llm_events(recorder)
    assert (start["event_type"], err["event_type"]) == ("llm_start", "llm_error")
    assert "mid-stream" in err["payload"]["error"]


def test_stream_helper_early_break_records_partial_usage(recorder):
    patch_anthropic()
    with sync_client().messages.stream(**REQUEST) as stream:
        for _ in stream:
            break
    start, end = llm_events(recorder)
    assert (start["event_type"], end["event_type"]) == ("llm_start", "llm_end")
    assert end["payload"]["prompt_tokens"] == 12
    assert end["payload"]["completion_tokens"] == 1


def test_api_error_emits_llm_error_and_reraises(recorder):
    patch_anthropic()
    with pytest.raises(anthropic.BadRequestError):
        sync_client().messages.create(**{**REQUEST, "model": "fail"})
    start, err = llm_events(recorder)
    assert err["event_type"] == "llm_error"
    assert err["status"] == "error"
    assert "bad model" in err["payload"]["error"]


def test_calls_nest_under_traced_function(recorder):
    patch_anthropic()

    @trace(name="planner", agent_type="agent")
    def plan():
        return sync_client().messages.create(**REQUEST)

    plan()
    chain = [e for e in recorder.events if e["agent_type"] == "agent"]
    llm = llm_events(recorder)
    assert chain and llm
    assert all(e["parent_event_id"] == chain[0]["event_id"] for e in llm)


def test_patch_is_idempotent_and_unpatch_restores():
    originals = (Messages.create, AsyncMessages.create, Messages.stream)
    assert patch_anthropic() is True
    patched = Messages.create
    assert patch_anthropic() is True
    assert Messages.create is patched  # not double-wrapped
    unpatch_anthropic()
    assert (Messages.create, AsyncMessages.create, Messages.stream) == originals


def test_returns_false_when_sdk_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", None)
    assert patch_anthropic() is False


def test_incompatible_sdk_layout_raises(monkeypatch):
    import types

    fake = types.ModuleType("anthropic.resources.messages")
    monkeypatch.setitem(sys.modules, "anthropic.resources.messages", fake)
    with pytest.raises(AgentScopeError, match="not supported"):
        patch_anthropic()


@pytest.mark.parametrize(
    "content,expected",
    [
        ("plain", "plain"),
        ([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}], "ab"),
        ([{"type": "image", "source": {}}], "[image]"),
        (
            [{"type": "tool_result", "tool_use_id": "t1", "content": "x"}],
            "[tool_result t1]",
        ),
        ([{"type": "thinking", "thinking": "hidden"}], ""),
        (None, ""),
    ],
)
def test_content_rendering(content, expected):
    assert provider._content_text(content) == expected
