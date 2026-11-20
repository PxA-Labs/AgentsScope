"""patch_gemini against the real google-genai SDK with a mocked HTTP transport."""

import asyncio
import json
import sys

import pytest

genai = pytest.importorskip("google.genai")

# google-genai picks httpx or httpx2 based on the injected client's type.
try:
    import httpx2 as httpx
except ImportError:  # pragma: no cover - depends on installed SDK version
    httpx = pytest.importorskip("httpx")

from google.genai import types  # noqa: E402
from google.genai.models import AsyncModels, Models  # noqa: E402

from agentscope import trace  # noqa: E402
from agentscope._pricing import calculate_cost  # noqa: E402
from agentscope.exceptions import AgentScopeError  # noqa: E402
from agentscope.providers import gemini as provider  # noqa: E402
from agentscope.providers.gemini import patch_gemini, unpatch_gemini  # noqa: E402

MODEL = "gemini-1.5-flash"

RESPONSE = {
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {"text": "Paris."},
                    {"functionCall": {"name": "lookup", "args": {"q": "fr"}}},
                ],
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {
        "promptTokenCount": 8,
        "candidatesTokenCount": 3,
        "totalTokenCount": 13,
        "thoughtsTokenCount": 2,
    },
}

STREAM_CHUNKS = [
    {
        "candidates": [{"content": {"role": "model", "parts": [{"text": "Par"}]}}],
        "usageMetadata": {"promptTokenCount": 8, "totalTokenCount": 8},
    },
    {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": "is."}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 8,
            "candidatesTokenCount": 3,
            "totalTokenCount": 11,
        },
    },
]


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if "/models/fail:" in path:
        return httpx.Response(
            400,
            json={
                "error": {
                    "code": 400,
                    "message": "bad model",
                    "status": "INVALID_ARGUMENT",
                }
            },
        )
    if path.endswith(":streamGenerateContent"):
        body = "".join(f"data: {json.dumps(c)}\r\n\r\n" for c in STREAM_CHUNKS)
        return httpx.Response(
            200, content=body.encode(), headers={"content-type": "text/event-stream"}
        )
    return httpx.Response(200, json=RESPONSE)


def make_client():
    return genai.Client(
        api_key="test",
        http_options=types.HttpOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handler)),
            httpx_async_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler)
            ),
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
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
    unpatch_gemini()


def llm_events(rec):
    return [e for e in rec.events if e["agent_type"] == "llm"]


CONFIG = types.GenerateContentConfig(system_instruction="Be brief", temperature=0.2)


def assert_events(rec, completion, streaming, completion_tokens, total, details):
    start, end = llm_events(rec)
    assert (start["event_type"], end["event_type"]) == ("llm_start", "llm_end")
    assert start["event_id"] == end["event_id"]
    assert end["agent_name"] == f"Gemini:{MODEL}"
    payload = end["payload"]
    assert payload["prompts"] == ["system: Be brief", "user: Capital of France?"]
    assert payload["temperature"] == 0.2
    assert payload["streaming"] is streaming
    assert payload["completion"] == completion
    assert payload["prompt_tokens"] == 8
    assert payload["completion_tokens"] == completion_tokens
    assert payload["total_tokens"] == total
    assert payload["cost_usd"] > 0
    assert payload.get("usage_details", {}) == details


def test_sync_generate_content(recorder):
    assert patch_gemini() is True
    res = make_client().models.generate_content(
        model=MODEL, contents="Capital of France?", config=CONFIG
    )
    assert res.candidates[0].content.parts[0].text == "Paris."
    assert_events(
        recorder,
        'Paris.[function_call lookup: {"q": "fr"}]',
        streaming=False,
        completion_tokens=5,  # 3 candidate + 2 thought tokens
        total=13,
        details={"thoughts_token_count": 2},
    )


def test_thought_tokens_count_as_completion_tokens_and_cost(recorder):
    # Google bills thinking tokens at the output rate, so they belong in
    # completion_tokens and the cost estimate (Anthropic already includes
    # thinking in output_tokens).
    patch_gemini()
    make_client().models.generate_content(
        model=MODEL, contents="Capital of France?", config=CONFIG
    )
    payload = llm_events(recorder)[-1]["payload"]
    assert payload["completion_tokens"] == 5
    assert payload["cost_usd"] == calculate_cost(MODEL, 8, 5)
    assert payload["usage_details"]["thoughts_token_count"] == 2


@pytest.mark.parametrize(
    "meta,expected",
    [
        ({"prompt_token_count": 8, "candidates_token_count": 3}, (8, 3, 11)),
        (
            {
                "prompt_token_count": 8,
                "candidates_token_count": 3,
                "thoughts_token_count": 2,
            },
            (8, 5, 13),
        ),
        # Early stream chunks can carry thoughts before any candidate tokens.
        ({"prompt_token_count": 8, "thoughts_token_count": 4}, (8, 4, 12)),
        ({"prompt_token_count": 8, "total_token_count": 8}, (8, None, 8)),
    ],
)
def test_usage_includes_thoughts(meta, expected):
    assert provider._usage({"usage_metadata": meta}) == expected


def test_models_prefix_is_normalised(recorder):
    patch_gemini()
    make_client().models.generate_content(
        model=f"models/{MODEL}", contents="Capital of France?", config=CONFIG
    )
    assert llm_events(recorder)[-1]["payload"]["model"] == MODEL


@pytest.mark.parametrize(
    "model",
    [
        MODEL,
        f"models/{MODEL}",
        f"publishers/google/models/{MODEL}",
        f"projects/p/locations/us-central1/publishers/google/models/{MODEL}",
    ],
)
def test_model_name_is_normalised(model):
    assert provider._ADAPTER.model({"model": model}) == MODEL


def test_async_generate_content(recorder):
    patch_gemini()

    async def run():
        return await make_client().aio.models.generate_content(
            model=MODEL, contents="Capital of France?", config=CONFIG
        )

    asyncio.run(run())
    assert_events(
        recorder,
        'Paris.[function_call lookup: {"q": "fr"}]',
        False,
        5,
        13,
        {"thoughts_token_count": 2},
    )


def test_sync_generate_content_stream(recorder):
    patch_gemini()
    stream = make_client().models.generate_content_stream(
        model=MODEL, contents="Capital of France?", config=CONFIG
    )
    assert llm_events(recorder)[0]["event_type"] == "llm_start"
    text = "".join(chunk.text for chunk in stream)
    assert text == "Paris."
    assert_events(recorder, "Paris.", True, 3, 11, {})


def test_async_generate_content_stream(recorder):
    patch_gemini()

    async def run():
        stream = await make_client().aio.models.generate_content_stream(
            model=MODEL, contents="Capital of France?", config=CONFIG
        )
        return "".join([chunk.text async for chunk in stream])

    assert asyncio.run(run()) == "Paris."
    assert_events(recorder, "Paris.", True, 3, 11, {})


def test_api_error_emits_llm_error_and_reraises(recorder):
    patch_gemini()
    with pytest.raises(genai.errors.ClientError):
        make_client().models.generate_content(model="fail", contents="hi")
    start, err = llm_events(recorder)
    assert err["event_type"] == "llm_error"
    assert "bad model" in err["payload"]["error"]


def test_stream_error_during_iteration_emits_llm_error(recorder):
    patch_gemini()
    stream = make_client().models.generate_content_stream(model="fail", contents="hi")
    with pytest.raises(genai.errors.ClientError):
        list(stream)
    assert llm_events(recorder)[-1]["event_type"] == "llm_error"


def test_calls_nest_under_traced_function(recorder):
    patch_gemini()

    @trace(name="planner", agent_type="agent")
    def plan():
        return make_client().models.generate_content(model=MODEL, contents="hi")

    plan()
    agent = [e for e in recorder.events if e["agent_type"] == "agent"]
    assert all(
        e["parent_event_id"] == agent[0]["event_id"] for e in llm_events(recorder)
    )


def test_patch_is_idempotent_and_unpatch_restores():
    originals = (Models.generate_content, AsyncModels.generate_content_stream)
    assert patch_gemini() is True
    patched = Models.generate_content
    assert patch_gemini() is True
    assert Models.generate_content is patched
    unpatch_gemini()
    assert (Models.generate_content, AsyncModels.generate_content_stream) == originals


def test_returns_false_when_sdk_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "google.genai", None)
    assert patch_gemini() is False


def test_incompatible_sdk_layout_raises(monkeypatch):
    import types as pytypes

    monkeypatch.setitem(
        sys.modules, "google.genai.models", pytypes.ModuleType("google.genai.models")
    )
    with pytest.raises(AgentScopeError, match="not supported"):
        patch_gemini()


@pytest.mark.parametrize(
    "contents,expected",
    [
        ("hi", ["user: hi"]),
        (["a", "b"], ["user: a", "user: b"]),
        (
            [
                {"role": "user", "parts": [{"text": "q"}]},
                {"role": "model", "parts": [{"text": "a"}]},
            ],
            ["user: q", "model: a"],
        ),
        ([["x", "y"]], ["user: xy"]),
    ],
)
def test_prompt_rendering(contents, expected):
    assert provider._extract_prompts({"contents": contents}) == expected
