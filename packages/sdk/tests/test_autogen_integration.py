"""AutoGen integration against real autogen-agentchat teams.

Uses AutoGen's own ReplayChatCompletionClient (scripted responses, no network),
so agents, tool execution, termination and streaming are all AutoGen's.
"""

import asyncio
import time

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

from agentscope_trace._pricing import calculate_cost  # noqa: E402
from agentscope_trace.decorators import current_parent_run_id, trace  # noqa: E402
from agentscope_trace.integrations.autogen import (  # noqa: E402
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
        "agentscope_trace.integrations.autogen.get_global_client", lambda: rec
    )
    monkeypatch.setattr("agentscope_trace.decorators.get_global_client", lambda: rec)
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


class SlowClient(ReplayChatCompletionClient):
    """A replay client whose calls take a while, so a team keeps talking."""

    def __init__(self, *args, calls, **kwargs):
        super().__init__(*args, **kwargs)
        self._calls = calls

    async def create(self, *args, **kwargs):
        self._calls.append(time.perf_counter())
        await asyncio.sleep(0.01)
        return await super().create(*args, **kwargs)


def make_chatty_team(rec, calls, turns=20):
    def agent(name):
        client = SlowClient(
            [f"{name}{i}" for i in range(turns)], model_info=INFO, calls=calls
        )
        return AssistantAgent(
            name,
            model_client=trace_model_client(
                client, name="gpt-4o", agentscope_client=rec
            ),
        )

    return RoundRobinGroupChat(
        [agent("a"), agent("b")], termination_condition=MaxMessageTermination(turns)
    )


def run_end_is_last(rec):
    """True when no event is emitted after the run node closes."""
    ends = [
        i
        for i, e in enumerate(rec.events)
        if e["agent_type"] == "team" and e["status"] != "running"
    ]
    return ends == [len(rec.events) - 1]


@pytest.mark.parametrize("close", ["aclose", "break"])
def test_tracer_run_stream_stops_the_team_on_early_close(close):
    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)

    async def main():
        tracer = AgentScopeAutoGenTracer(agentscope_client=rec)
        if close == "aclose":
            stream = tracer.run_stream(team, task="go")
            await stream.__anext__()
            await stream.aclose()
        else:
            async for _ in tracer.run_stream(team, task="go"):
                break
            for _ in range(5):  # let asyncio finalize the abandoned stream
                await asyncio.sleep(0.01)
        closed_at = time.perf_counter()
        await asyncio.sleep(0.3)
        await team.reset()  # raises if the team is still running
        return closed_at

    closed_at = asyncio.run(main())

    assert calls and not [c for c in calls if c > closed_at]
    assert len(calls) < 5  # stopped, not run to its 20-message limit
    (team_node,) = of(final_nodes(rec), "team")
    assert team_node["event_type"] == "chain_end"
    assert team_node["payload"]["outputs"]["closed_early"] is True
    assert "cancelled" not in team_node["payload"]["outputs"]  # a close
    assert run_end_is_last(rec)
    assert rec.status == ["completed"]


def test_trace_cancels_the_callers_token_on_early_close():
    from autogen_core import CancellationToken

    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)
    token = CancellationToken()

    async def main():
        stream = AgentScopeAutoGenTracer(agentscope_client=rec).trace(
            team.run_stream(task="go", cancellation_token=token),
            task="go",
            cancellation_token=token,
        )
        await stream.__anext__()
        await stream.aclose()
        closed_at = time.perf_counter()
        await asyncio.sleep(0.3)
        return closed_at

    closed_at = asyncio.run(main())

    assert token.is_cancelled()
    assert not [c for c in calls if c > closed_at]
    assert len(calls) < 5
    assert run_end_is_last(rec)
    assert rec.status == ["completed"]


def test_aclose_without_a_token_waits_for_the_team_then_closes_the_run():
    # Without a token AutoGen's own aclose() lets the team run until it goes
    # idle. The run node stays open until then, so every LLM call made while
    # closing is recorded under the run, never after it ended.
    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)

    async def main():
        stream = AgentScopeAutoGenTracer(agentscope_client=rec).trace(
            team.run_stream(task="go"), task="go"
        )
        await stream.__anext__()
        calls_at_close = len(calls)
        await stream.aclose()
        await team.reset()  # the team is idle once aclose() returns
        return calls_at_close

    calls_at_close = asyncio.run(main())

    assert len(calls) > calls_at_close  # the team kept going while closing
    assert run_end_is_last(rec)
    (team_node,) = of(final_nodes(rec), "team")
    run_id = team_node["event_id"]
    llm_nodes = of(final_nodes(rec), "llm")
    assert llm_nodes and all(n["parent_event_id"] == run_id for n in llm_nodes)
    assert team_node["payload"]["outputs"]["closed_early"] is True
    assert rec.status == ["completed"]


async def wait_for_calls(calls, n):
    while len(calls) < n:
        await asyncio.sleep(0.001)


def run_ends(rec):
    return [
        e for e in rec.events if e["agent_type"] == "team" and e["status"] != "running"
    ]


def assert_recorded_as_cancelled(rec):
    (end,) = run_ends(rec)  # recorded exactly once
    assert end["event_type"] == "chain_end" and end["status"] == "completed"
    assert end["payload"]["outputs"]["closed_early"] is True
    assert end["payload"]["outputs"]["cancelled"] is True
    assert run_end_is_last(rec)
    assert rec.status == ["completed"]


def assert_team_stopped(calls, cancelled_at):
    # At most one call can start in the loop iteration before the cancellation
    # is delivered; the 20-message conversation must not carry on.
    assert len([c for c in calls if c > cancelled_at]) <= 1
    assert len(calls) < 6


def test_cancelling_the_consumer_task_stops_the_team():
    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)

    async def main():
        tracer = AgentScopeAutoGenTracer(agentscope_client=rec)

        async def consume():
            async for _ in tracer.run_stream(team, task="go"):
                pass

        consumer = asyncio.create_task(consume())
        await wait_for_calls(calls, 2)  # the consumer is awaiting the next item
        cancelled_at = time.perf_counter()
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
        assert consumer.cancelled()
        await asyncio.sleep(0.3)
        await team.reset()  # raises if the team is still running
        return cancelled_at

    cancelled_at = asyncio.run(main())

    assert_team_stopped(calls, cancelled_at)
    assert_recorded_as_cancelled(rec)


def test_cancelling_tracer_run_stops_the_team():
    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)

    async def main():
        runner = asyncio.create_task(
            AgentScopeAutoGenTracer(agentscope_client=rec).run(team, task="go")
        )
        await wait_for_calls(calls, 2)
        cancelled_at = time.perf_counter()
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        assert runner.cancelled()
        await asyncio.sleep(0.3)
        await team.reset()
        return cancelled_at

    cancelled_at = asyncio.run(main())

    assert_team_stopped(calls, cancelled_at)
    assert_recorded_as_cancelled(rec)


def test_timeout_around_tracer_run_stops_the_team_and_raises_timeout_error():
    # asyncio.timeout() cancels the task and relies on Task.uncancel() to turn
    # the CancelledError into TimeoutError, so the cancellation must propagate
    # unchanged and leave the task's cancel count balanced.
    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)

    async def main():
        tracer = AgentScopeAutoGenTracer(agentscope_client=rec)
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.03):
                await tracer.run(team, task="go")
        timed_out_at = time.perf_counter()
        assert asyncio.current_task().cancelling() == 0
        await asyncio.sleep(0.3)
        await team.reset()
        return timed_out_at

    timed_out_at = asyncio.run(main())

    assert_team_stopped(calls, timed_out_at)
    assert_recorded_as_cancelled(rec)


def test_cancelling_the_callers_token_is_recorded_as_cancelled():
    from autogen_core import CancellationToken

    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls)
    token = CancellationToken()

    async def main():
        runner = asyncio.create_task(
            AgentScopeAutoGenTracer(agentscope_client=rec).run(
                team, task="go", cancellation_token=token
            )
        )
        await wait_for_calls(calls, 2)
        cancelled_at = time.perf_counter()
        token.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
        return cancelled_at

    cancelled_at = asyncio.run(main())

    assert_team_stopped(calls, cancelled_at)
    assert_recorded_as_cancelled(rec)


def test_cancelling_the_consumer_of_trace_without_a_token_is_recorded_as_cancelled():
    # Without a token the tracer cannot stop the team (AutoGen waits for it to
    # go idle), but the run is still a cancellation, not a failure.
    rec, calls = Recorder(), []
    team = make_chatty_team(rec, calls, turns=6)

    async def main():
        tracer = AgentScopeAutoGenTracer(agentscope_client=rec)

        async def consume():
            async for _ in tracer.trace(team.run_stream(task="go"), task="go"):
                pass

        consumer = asyncio.create_task(consume())
        await wait_for_calls(calls, 2)
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer

    asyncio.run(main())

    assert_recorded_as_cancelled(rec)


def test_item_arriving_as_the_consumer_is_cancelled_closes_the_stream():
    # The next item is ready in the same loop iteration as the cancellation:
    # the stream is then paused at its ``yield`` and must be closed.
    from autogen_core import CancellationToken

    rec, closed, token = Recorder(), [], CancellationToken()

    async def main():
        ready = asyncio.get_running_loop().create_future()

        async def stream():
            try:
                yield "first"
                yield await ready
                yield "never reached"
            finally:
                closed.append(True)

        async def consume():
            tracer = AgentScopeAutoGenTracer(agentscope_client=rec)
            async for _ in tracer.trace(stream(), task="t", cancellation_token=token):
                pass

        consumer = asyncio.create_task(consume())
        for _ in range(5):
            await asyncio.sleep(0)
        ready.set_result("second")
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer

    asyncio.run(main())

    assert token.is_cancelled()
    assert closed == [True]
    assert_recorded_as_cancelled(rec)


def test_second_cancellation_stops_waiting_for_a_stream_that_ignores_the_token():
    from autogen_core import CancellationToken

    rec, closed, token = Recorder(), [], CancellationToken()

    async def main():
        async def stubborn():
            try:
                yield "first"
                await asyncio.sleep(30)  # not linked to the token
            finally:
                closed.append(True)

        async def consume():
            tracer = AgentScopeAutoGenTracer(agentscope_client=rec)
            async for _ in tracer.trace(stubborn(), task="t", cancellation_token=token):
                pass

        consumer = asyncio.create_task(consume())
        for _ in range(5):
            await asyncio.sleep(0)
        consumer.cancel()
        await asyncio.sleep(0.05)
        assert not consumer.done()  # waiting for the stream to stop
        consumer.cancel()
        async with asyncio.timeout(5):
            with pytest.raises(asyncio.CancelledError):
                await consumer

    asyncio.run(main())

    assert token.is_cancelled()
    assert closed == [True]
    assert_recorded_as_cancelled(rec)


def test_events_follow_reconfigured_global_client(monkeypatch):
    import agentscope_trace.decorators as decorators

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
        "agentscope_trace.integrations.autogen.get_global_client", lambda: rec
    )
    wrapped = trace_model_client(
        ReplayChatCompletionClient(["restored"], model_info=INFO), name="gpt-4o"
    )
    config = wrapped.dump_component()
    assert (
        config.provider
        == "agentscope_trace.integrations.autogen.TracedChatCompletionClient"
    )

    loaded = ChatCompletionClient.load_component(config)
    assert getattr(loaded, "_agentscope_traced", False)
    asyncio.run(loaded.create([UserMessage(content="hi", source="u")]))
    (end,) = [e for e in rec.events if e["event_type"] == "llm_end"]
    assert end["agent_name"] == "gpt-4o"
    assert end["payload"]["completion"] == "restored"

    # Agents (and so teams) holding a traced client can be dumped too.
    AssistantAgent("a", model_client=wrapped).dump_component()
