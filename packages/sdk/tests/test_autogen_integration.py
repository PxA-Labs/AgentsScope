"""AutoGen integration against real autogen-agentchat teams.

Uses AutoGen's own ReplayChatCompletionClient (scripted responses, no network),
so agents, tool execution, termination and streaming are all AutoGen's.
"""

import asyncio

import pytest

pytest.importorskip("autogen_agentchat")
replay = pytest.importorskip("autogen_ext.models.replay")

from autogen_agentchat.agents import AssistantAgent  # noqa: E402
from autogen_agentchat.conditions import (  # noqa: E402
    MaxMessageTermination,
    TextMentionTermination,
)
from autogen_agentchat.teams import RoundRobinGroupChat  # noqa: E402
from autogen_core import FunctionCall  # noqa: E402
from autogen_core.models import (  # noqa: E402
    CreateResult,
    ModelInfo,
    RequestUsage,
    SystemMessage,
    UserMessage,
)

from agentscope._pricing import calculate_cost  # noqa: E402
from agentscope.decorators import current_parent_run_id, trace  # noqa: E402
from agentscope.integrations.autogen import (  # noqa: E402
    AgentScopeAutoGenTracer,
    trace_model_client,
)

ReplayChatCompletionClient = replay.ReplayChatCompletionClient
INFO = ModelInfo(
    vision=False,
    function_calling=True,
    json_output=False,
    family="gpt-4o",
    structured_output=False,
)


class Recorder:
    def __init__(self):
        self.events = []
        self.status = []

    def emit(self, event):
        self.events.append(event)

    def patch_session_status(self, status):
        self.status.append(status)


def usage(prompt, completion):
    return RequestUsage(prompt_tokens=prompt, completion_tokens=completion)


def tool_call_result(name="lookup", args='{"q": "paris"}', call_id="call_1"):
    return CreateResult(
        finish_reason="function_calls",
        content=[FunctionCall(id=call_id, name=name, arguments=args)],
        usage=usage(30, 5),
        cached=False,
    )


async def lookup(q: str) -> str:
    """Look up a fact."""
    return f"fact about {q}"


async def broken_tool(q: str) -> str:
    """Always fails."""
    raise ValueError("backend down")


class FailingClient(ReplayChatCompletionClient):
    async def create(self, messages, **kwargs):
        raise RuntimeError("provider unavailable")


def make_team(rec, researcher_tools=(lookup,), researcher_script=None):
    researcher_client = ReplayChatCompletionClient(
        researcher_script or [tool_call_result(), "Paris is the capital."],
        model_info=INFO,
    )
    writer_client = ReplayChatCompletionClient(
        ["Article done. TERMINATE"], model_info=INFO
    )
    researcher = AssistantAgent(
        "researcher",
        model_client=trace_model_client(
            researcher_client, name="gpt-4o", agentscope_client=rec
        ),
        tools=list(researcher_tools),
        reflect_on_tool_use=True,
    )
    writer = AssistantAgent(
        "writer",
        model_client=trace_model_client(
            writer_client, name="gpt-4o", agentscope_client=rec
        ),
    )
    return RoundRobinGroupChat(
        [researcher, writer],
        termination_condition=TextMentionTermination("TERMINATE")
        | MaxMessageTermination(8),
    )


def final_nodes(rec):
    nodes = {}
    for e in rec.events:
        nodes[e["event_id"]] = e
    return nodes


def of(nodes, agent_type, name=None):
    return [
        n
        for n in nodes.values()
        if n["agent_type"] == agent_type and (name is None or n["agent_name"] == name)
    ]


def test_team_run_produces_structure_and_llm_usage():
    rec = Recorder()
    tracer = AgentScopeAutoGenTracer(name="paris-team", agentscope_client=rec)
    result = asyncio.run(tracer.run(make_team(rec), task="Write about Paris"))
    assert result.stop_reason == "Text 'TERMINATE' mentioned"

    nodes = final_nodes(rec)
    (team,) = of(nodes, "team")
    (researcher,) = of(nodes, "agent", "researcher")
    (writer,) = of(nodes, "agent", "writer")
    (tool,) = of(nodes, "tool")
    llms = of(nodes, "llm")

    assert team["agent_name"] == "paris-team" and team["parent_event_id"] is None
    assert (
        researcher["parent_event_id"] == writer["parent_event_id"] == team["event_id"]
    )
    assert tool["parent_event_id"] == researcher["event_id"]
    assert all(n["status"] == "completed" for n in nodes.values())

    assert tool["payload"]["input"] == '{"q": "paris"}'
    assert tool["payload"]["output"] == "fact about paris"

    # LLM calls come from the traced model clients and nest under the run.
    assert len(llms) == 3
    assert all(n["parent_event_id"] == team["event_id"] for n in llms)
    assert sorted(n["payload"]["total_tokens"] for n in llms) == [27, 30, 35]
    first = next(n for n in llms if n["payload"]["total_tokens"] == 35)
    assert first["payload"]["completion"] == '[function_call lookup: {"q": "paris"}]'
    assert first["payload"]["cost_usd"] == pytest.approx(
        calculate_cost("gpt-4o", 30, 5)
    )

    # Turn nodes carry AutoGen's usage as information only (no token fields).
    assert researcher["payload"]["outputs"]["output"] == "Paris is the capital."
    assert researcher["payload"]["outputs"]["models_usage"] == {
        "prompt_tokens": 53,
        "completion_tokens": 9,
    }
    assert "total_tokens" not in researcher["payload"]

    outputs = team["payload"]["outputs"]
    assert outputs["stop_reason"] == "Text 'TERMINATE' mentioned"
    assert outputs["final_message"] == "Article done. TERMINATE"
    assert rec.status == ["completed"]


def test_trace_yields_the_stream_unchanged():
    async def collect(stream):
        return [type(item).__name__ for item in [x async for x in stream]]

    plain = asyncio.run(collect(make_team(Recorder()).run_stream(task="t")))
    rec = Recorder()
    traced_stream = AgentScopeAutoGenTracer(agentscope_client=rec).trace(
        make_team(rec).run_stream(task="t"), task="t"
    )
    assert asyncio.run(collect(traced_stream)) == plain


def test_tool_error_is_recorded():
    rec = Recorder()
    team = make_team(
        rec,
        researcher_tools=(broken_tool,),
        researcher_script=[
            tool_call_result(name="broken_tool"),
            "Could not look it up.",
        ],
    )
    asyncio.run(AgentScopeAutoGenTracer(agentscope_client=rec).run(team, task="t"))
    (tool,) = of(final_nodes(rec), "tool")
    assert tool["event_type"] == "tool_error" and tool["status"] == "error"
    assert "backend down" in tool["payload"]["error"]


def test_llm_failure_marks_llm_turn_and_run_failed():
    rec = Recorder()
    agent = AssistantAgent(
        "flaky",
        model_client=trace_model_client(
            FailingClient([], model_info=INFO), name="gpt-4o", agentscope_client=rec
        ),
    )
    team = RoundRobinGroupChat([agent], termination_condition=MaxMessageTermination(3))
    with pytest.raises(Exception, match="provider unavailable"):
        asyncio.run(AgentScopeAutoGenTracer(agentscope_client=rec).run(team, task="t"))

    nodes = final_nodes(rec)
    (llm,) = of(nodes, "llm")
    assert llm["event_type"] == "llm_error"
    assert llm["payload"]["error"] == "provider unavailable"
    (team_node,) = of(nodes, "team")
    assert team_node["event_type"] == "chain_error"
    assert rec.status == ["failed"]


def test_model_client_standalone_and_nested_under_trace(monkeypatch):
    rec = Recorder()
    # The integration resolves the global client from its own module namespace.
    monkeypatch.setattr(
        "agentscope.integrations.autogen.get_global_client", lambda: rec
    )
    monkeypatch.setattr("agentscope.decorators.get_global_client", lambda: rec)
    client = trace_model_client(
        ReplayChatCompletionClient(["hello", "again"], model_info=INFO), name="gpt-4o"
    )
    messages = [
        SystemMessage(content="be brief"),
        UserMessage(content="hi", source="user"),
    ]
    asyncio.run(client.create(messages))
    start, end = rec.events
    assert start["parent_event_id"] is None
    assert start["payload"]["prompts"] == ["system: be brief", "user(user): hi"]
    assert end["payload"]["completion"] == "hello"

    @trace(name="outer")
    def outer():
        return asyncio.run(client.create(messages))

    outer()
    outer_id = next(e["event_id"] for e in rec.events if e["agent_name"] == "outer")
    llm = [e for e in rec.events if e["agent_type"] == "llm"][-1]
    assert llm["parent_event_id"] == outer_id


def test_model_client_streaming_emits_one_llm_end():
    rec = Recorder()
    client = trace_model_client(
        ReplayChatCompletionClient(["streamed answer"], model_info=INFO),
        name="gpt-4o",
        agentscope_client=rec,
    )

    async def consume():
        return [
            x
            async for x in client.create_stream([UserMessage(content="hi", source="u")])
        ]

    items = asyncio.run(consume())
    assert isinstance(items[-1], CreateResult)
    ends = [e for e in rec.events if e["event_type"] == "llm_end"]
    assert len(ends) == 1
    assert ends[0]["payload"]["completion"] == "streamed answer"
    assert ends[0]["payload"]["streaming"] is True


def test_wrapper_is_idempotent_and_delegates():
    inner = ReplayChatCompletionClient(["x"], model_info=INFO)
    wrapped = trace_model_client(inner, agentscope_client=Recorder())
    assert trace_model_client(wrapped) is wrapped
    assert wrapped.model_info == inner.model_info
    assert wrapped.capabilities == inner.capabilities
    assert wrapped.total_usage() == inner.total_usage()
    msgs = [UserMessage(content="count me", source="u")]
    assert wrapped.count_tokens(msgs) == inner.count_tokens(msgs)


def test_breaking_out_early_is_a_normal_close_and_restores_context():
    rec = Recorder()
    standalone = trace_model_client(
        ReplayChatCompletionClient(["unrelated"], model_info=INFO),
        name="gpt-4o",
        agentscope_client=rec,
    )
    loop_errors = []

    async def main():
        asyncio.get_running_loop().set_exception_handler(
            lambda loop, ctx: loop_errors.append(ctx)
        )
        tracer = AgentScopeAutoGenTracer(agentscope_client=rec)
        async for _ in tracer.trace(make_team(rec).run_stream(task="t"), task="t"):
            break  # abandon the stream; asyncio finalizes it in another Context
        parent_after_break = current_parent_run_id.get()
        for _ in range(20):
            await asyncio.sleep(0.01)
        await standalone.create([UserMessage(content="hi", source="u")])
        return parent_after_break

    parent_after_break = asyncio.run(main())

    assert parent_after_break is None
    assert loop_errors == []
    nodes = final_nodes(rec)
    (team_node,) = of(nodes, "team")
    assert team_node["event_type"] == "chain_end"
    assert team_node["status"] == "completed"
    assert "failed" not in rec.status
    unrelated = [
        e
        for e in rec.events
        if e["agent_type"] == "llm" and e["payload"].get("completion") == "unrelated"
    ]
    assert unrelated and unrelated[-1]["parent_event_id"] is None


@pytest.mark.parametrize("kind", ["agent", "team"])
def test_breaking_out_and_returning_at_once_is_still_a_normal_close(kind):
    # No sleep after ``break``: the loop shuts down while the abandoned stream
    # is being finalized, and asyncio throws CancelledError (not GeneratorExit)
    # into it. That is still the consumer closing the stream, not a failure.
    rec = Recorder()

    async def main():
        if kind == "agent":
            runner = AssistantAgent(
                "solo",
                model_client=trace_model_client(
                    ReplayChatCompletionClient(["x"] * 5, model_info=INFO),
                    agentscope_client=rec,
                ),
            )
        else:
            runner = make_team(rec)
        tracer = AgentScopeAutoGenTracer(agentscope_client=rec)
        async for _ in tracer.trace(runner.run_stream(task="go"), task="go"):
            break

    asyncio.run(main())

    (team_node,) = of(final_nodes(rec), "team")
    assert team_node["event_type"] == "chain_end"
    assert team_node["payload"]["outputs"].get("closed_early") is True
    assert rec.status == ["completed"]


def test_explicit_aclose_closes_the_run_and_the_team():
    rec = Recorder()
    team = make_team(rec)

    async def main():
        traced = AgentScopeAutoGenTracer(agentscope_client=rec).trace(
            team.run_stream(task="t"), task="t"
        )
        await traced.__anext__()
        await traced.aclose()
        # The team was closed too: reset() raises while a team is still running.
        await team.reset()

    asyncio.run(main())
    (team_node,) = of(final_nodes(rec), "team")
    assert team_node["event_type"] == "chain_end"
    assert rec.status == ["completed"]


def test_events_follow_reconfigured_global_client(monkeypatch):
    import agentscope.decorators as decorators

    clients = []

    class FakeClient(Recorder):
        def __init__(self, session_name=None, **kwargs):
            super().__init__()
            self.session_name = session_name
            clients.append(self)

        def stop(self):
            pass

    monkeypatch.setattr(decorators, "AgentScopeClient", FakeClient)
    monkeypatch.setattr(decorators, "_global_client", None)

    decorators.configure(session_name="job-1")
    tracer = AgentScopeAutoGenTracer()
    model = trace_model_client(
        ReplayChatCompletionClient(["one", "two"], model_info=INFO), name="gpt-4o"
    )
    msgs = [UserMessage(content="hi", source="u")]
    asyncio.run(model.create(msgs))
    decorators.configure(session_name="job-2")
    asyncio.run(model.create(msgs))
    asyncio.run(tracer.run(make_team(Recorder()), task="t"))

    job1, job2 = clients
    assert [
        e["payload"]["completion"]
        for e in job1.events
        if e["payload"].get("completion")
    ] == ["one"]
    assert any(e["payload"].get("completion") == "two" for e in job2.events)
    assert any(e["agent_type"] == "team" for e in job2.events)
    assert job2.status == ["completed"] and job1.status == []


def test_traced_client_round_trips_through_dump_component(monkeypatch):
    from autogen_core.models import ChatCompletionClient

    rec = Recorder()
    monkeypatch.setattr(
        "agentscope.integrations.autogen.get_global_client", lambda: rec
    )
    wrapped = trace_model_client(
        ReplayChatCompletionClient(["restored"], model_info=INFO), name="gpt-4o"
    )
    config = wrapped.dump_component()
    assert (
        config.provider == "agentscope.integrations.autogen.TracedChatCompletionClient"
    )

    loaded = ChatCompletionClient.load_component(config)
    assert getattr(loaded, "_agentscope_traced", False)
    asyncio.run(loaded.create([UserMessage(content="hi", source="u")]))
    (end,) = [e for e in rec.events if e["event_type"] == "llm_end"]
    assert end["agent_name"] == "gpt-4o"
    assert end["payload"]["completion"] == "restored"

    # Agents (and so teams) holding a traced client can be dumped too.
    AssistantAgent("a", model_client=wrapped).dump_component()
