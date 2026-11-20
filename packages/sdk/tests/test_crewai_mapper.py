"""CrewAIEventMapper unit tests using lightweight fake events (no CrewAI)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentscope_trace._pricing import calculate_cost
from agentscope_trace.integrations.crewai import CrewAIEventMapper

T0 = datetime(2026, 11, 15, 12, 0, 0, tzinfo=timezone.utc)


class Recorder:
    def __init__(self):
        self.events = []
        self.status = []

    def emit(self, event):
        self.events.append(event)

    def patch_session_status(self, status):
        self.status.append(status)


def ev(type_, event_id, parent=None, started=None, seconds=0, **fields):
    return SimpleNamespace(
        type=type_,
        event_id=event_id,
        parent_event_id=parent,
        started_event_id=started,
        timestamp=T0 + timedelta(seconds=seconds),
        **fields,
    )


@pytest.fixture
def rec():
    return Recorder()


@pytest.fixture
def mapper(rec):
    return CrewAIEventMapper(rec)


def by_type(rec, event_type):
    return [e for e in rec.events if e["event_type"] == event_type]


def test_start_and_end_share_event_id_and_compute_latency(mapper, rec):
    mapper.handle(
        ev("crew_kickoff_started", "c1", crew_name="research", inputs={"q": 1})
    )
    mapper.handle(
        ev(
            "crew_kickoff_completed",
            "c2",
            started="c1",
            seconds=2,
            output="done",
            total_tokens=99,
        )
    )
    start, end = rec.events
    assert start["event_id"] == end["event_id"] == "c1"
    assert (start["event_type"], end["event_type"]) == ("chain_start", "chain_end")
    assert start["agent_type"] == "crew" and start["agent_name"] == "research"
    assert start["payload"]["inputs"] == {"q": 1}
    assert end["payload"]["outputs"] == {"output": "done", "crew_total_tokens": 99}
    assert end["latency_ms"] == 2000
    assert (start["status"], end["status"]) == ("running", "completed")
    assert rec.status == ["completed"]


def test_parent_resolves_through_hidden_internal_events(mapper, rec):
    mapper.handle(ev("crew_kickoff_started", "c1"))
    mapper.handle(ev("task_started", "t1", parent="c1", task_name="Research"))
    mapper.handle(
        ev("agent_execution_started", "a1", parent="t1", agent_role="Researcher")
    )
    # CrewAI's agent executor is a Flow; it is not shown but is a parent.
    mapper.handle(ev("flow_started", "f1", parent="a1"))
    mapper.handle(ev("agent_logs_started", "l1", parent="f1"))
    mapper.handle(
        ev("llm_call_started", "m1", parent="f1", model="gpt-4o", messages="hi")
    )

    shown = {e["event_id"]: e for e in rec.events}
    assert set(shown) == {"c1", "t1", "a1", "m1"}, "internal events are not shown"
    assert shown["t1"]["parent_event_id"] == "c1"
    assert shown["a1"]["parent_event_id"] == "t1"
    assert shown["m1"]["parent_event_id"] == "a1", "flow_started is skipped"


def test_llm_events_carry_prompts_usage_and_cost(mapper, rec):
    mapper.handle(
        ev(
            "llm_call_started",
            "m1",
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "q"},
            ],
            temperature=0.3,
            stream=False,
        )
    )
    mapper.handle(
        ev(
            "llm_call_completed",
            "m2",
            started="m1",
            seconds=1,
            model="gpt-4o",
            response="answer",
            usage={"prompt_tokens": 100, "completion_tokens": 20},
        )
    )
    start, end = rec.events
    assert start["agent_name"] == "gpt-4o"
    assert start["payload"]["prompts"] == ["system: be brief", "user: q"]
    assert start["payload"]["temperature"] == 0.3
    payload = end["payload"]
    assert payload["completion"] == "answer"
    assert (
        payload["prompt_tokens"],
        payload["completion_tokens"],
        payload["total_tokens"],
    ) == (
        100,
        20,
        120,
    )
    assert payload["cost_usd"] == pytest.approx(calculate_cost("gpt-4o", 100, 20))


def test_llm_usage_accepts_input_output_token_names(mapper, rec):
    mapper.handle(
        ev(
            "llm_call_completed",
            "m2",
            started="m1",
            model="claude-3-haiku",
            response="x",
            usage={"input_tokens": 5, "output_tokens": 7},
        )
    )
    assert rec.events[0]["payload"]["total_tokens"] == 12


def test_tool_events(mapper, rec):
    mapper.handle(
        ev("tool_usage_started", "u1", tool_name="search", tool_args={"q": "x"})
    )
    mapper.handle(
        ev(
            "tool_usage_finished",
            "u2",
            started="u1",
            tool_name="search",
            tool_args={"q": "x"},
            output="result",
            from_cache=True,
        )
    )
    start, end = rec.events
    assert start["agent_type"] == "tool" and start["agent_name"] == "search"
    assert start["payload"]["input"] == '{"q": "x"}'
    assert end["payload"]["output"] == "result"
    assert end["payload"]["from_cache"] is True


def test_failures_map_to_error_events_and_failed_session(mapper, rec):
    mapper.handle(ev("crew_kickoff_started", "c1"))
    mapper.handle(
        ev("tool_usage_started", "u1", parent="c1", tool_name="calc", tool_args="1/0")
    )
    mapper.handle(
        ev(
            "tool_usage_error",
            "u2",
            parent="c1",
            started="u1",
            tool_name="calc",
            error="ZeroDivisionError",
        )
    )
    mapper.handle(
        ev(
            "llm_call_failed",
            "m2",
            parent="c1",
            started="m1",
            model="gpt-4o",
            error="rate limited",
        )
    )
    mapper.handle(
        ev("crew_kickoff_failed", "c2", started="c1", error=RuntimeError("boom"))
    )

    tool_err = by_type(rec, "tool_error")[0]
    assert tool_err["event_id"] == "u1" and tool_err["status"] == "error"
    assert tool_err["payload"]["error"] == "ZeroDivisionError"
    llm_err = by_type(rec, "llm_error")[0]
    assert llm_err["payload"]["error"] == "rate limited"
    crew_err = by_type(rec, "chain_error")[0]
    assert crew_err["event_id"] == "c1" and crew_err["payload"]["error"] == "boom"
    assert rec.status == ["failed"]


def test_session_status_patching_can_be_disabled(rec):
    mapper = CrewAIEventMapper(rec, mark_session_status=False)
    mapper.handle(ev("crew_kickoff_started", "c1"))
    mapper.handle(ev("crew_kickoff_completed", "c2", started="c1"))
    assert rec.status == []


def test_unknown_and_malformed_events_never_raise(mapper, rec):
    mapper.handle(ev("memory_query_started", "x1"))  # tracked for parents only
    mapper.handle(SimpleNamespace(type="task_started"))  # no event_id
    mapper.handle(object())  # completely foreign object
    assert rec.events == []


def test_emit_failures_are_swallowed(rec):
    class Broken(Recorder):
        def emit(self, event):
            raise RuntimeError("network down")

    CrewAIEventMapper(Broken()).handle(ev("crew_kickoff_started", "c1"))


def test_parent_cycles_do_not_hang(mapper, rec):
    mapper.handle(ev("flow_started", "a", parent="b"))
    mapper.handle(ev("flow_started", "b", parent="a"))
    mapper.handle(ev("task_started", "t", parent="a"))
    assert rec.events[0]["parent_event_id"] is None


def test_long_text_is_truncated(mapper, rec):
    mapper.handle(
        ev(
            "llm_call_completed",
            "m2",
            started="m1",
            model="gpt-4o",
            response="x" * 10_000,
        )
    )
    completion = rec.events[0]["payload"]["completion"]
    assert len(completion) == 4000 and completion.endswith("…")


def test_only_open_scopes_are_remembered(mapper, rec):
    for i in range(50):
        mapper.handle(ev("crew_kickoff_started", f"c{i}"))
        mapper.handle(ev("flow_started", f"f{i}", parent=f"c{i}"))
        mapper.handle(ev("llm_call_started", f"m{i}", parent=f"f{i}", model="x"))
        for j in range(20):  # e.g. streamed chunks: not scopes, never parents
            mapper.handle(ev("llm_stream_chunk", f"s{i}-{j}", parent=f"m{i}"))
        mapper.handle(
            ev("llm_call_completed", f"m{i}e", parent=f"f{i}", started=f"m{i}")
        )
        mapper.handle(ev("flow_finished", f"f{i}e", parent=f"c{i}", started=f"f{i}"))
        mapper.handle(ev("crew_kickoff_completed", f"c{i}e", started=f"c{i}"))
    assert (len(mapper._parents), len(mapper._shown), len(mapper._started_at)) == (
        0,
        0,
        0,
    )
    llm = [e for e in rec.events if e["event_type"] == "llm_start"][-1]
    assert llm["parent_event_id"] == "c49"


def test_only_the_root_crew_sets_session_status(mapper, rec):
    mapper.handle(ev("crew_kickoff_started", "c1", crew_name="outer"))
    mapper.handle(ev("tool_usage_started", "u1", parent="c1", tool_name="delegate"))
    # A crew kicked off from inside a tool of the outer crew.
    mapper.handle(ev("crew_kickoff_started", "n1", parent="u1", crew_name="inner"))
    mapper.handle(ev("crew_kickoff_failed", "n2", parent="u1", started="n1", error="x"))
    assert rec.status == [], "a nested crew must not set the session status"
    mapper.handle(
        ev("tool_usage_finished", "u2", parent="c1", started="u1", output="ok")
    )
    mapper.handle(ev("crew_kickoff_completed", "c2", started="c1", output="done"))
    assert rec.status == ["completed"]
    inner = [e for e in rec.events if e["event_id"] == "n1"]
    assert [e["status"] for e in inner] == ["running", "error"]
    assert all(e["parent_event_id"] == "u1" for e in inner)


# A user Flow vs. one of CrewAI's internal flows (AgentExecutor, memory), which
# declare the ``is_crewai_internal`` class marker. The bus passes the flow as
# the event's source.
class _UserFlow:
    is_crewai_internal = False

    def __init__(self, suppress_flow_events=False):
        self.suppress_flow_events = suppress_flow_events


class _InternalFlow(_UserFlow):
    is_crewai_internal = True


USER_FLOW = _UserFlow()
# ``suppress_flow_events`` only asks for console quiet; a user's flow may set it.
QUIET_USER_FLOW = _UserFlow(suppress_flow_events=True)
INTERNAL_FLOW = _InternalFlow(suppress_flow_events=True)


def flow_run(mapper, i, second_fails=False):
    """Replay a two-crew Flow the way CrewAI emits it (methods are hidden)."""
    f, m1, m2 = f"f{i}", f"f{i}-m1", f"f{i}-m2"
    mapper.handle(
        ev("flow_started", f, flow_name="TwoCrewFlow", inputs={"q": 1}), USER_FLOW
    )
    mapper.handle(ev("method_execution_started", m1, parent=f), USER_FLOW)
    mapper.handle(ev("crew_kickoff_started", f"{f}-c1", parent=m1, crew_name="one"))
    mapper.handle(
        ev("crew_kickoff_completed", f"{f}-c1e", parent=m1, started=f"{f}-c1")
    )
    mapper.handle(ev("method_execution_finished", f"{m1}e", parent=f, started=m1))
    mapper.handle(ev("method_execution_started", m2, parent=f), USER_FLOW)
    mapper.handle(ev("crew_kickoff_started", f"{f}-c2", parent=m2, crew_name="two"))
    end = "crew_kickoff_failed" if second_fails else "crew_kickoff_completed"
    mapper.handle(ev(end, f"{f}-c2e", parent=m2, started=f"{f}-c2", error="x"))
    end = "method_execution_failed" if second_fails else "method_execution_finished"
    mapper.handle(ev(end, f"{m2}e", parent=f, started=m2, error="x"))


def test_user_flow_is_a_node_and_crews_nest_under_it(mapper, rec):
    flow_run(mapper, 0)
    mapper.handle(
        ev("flow_finished", "f0e", started="f0", seconds=3, result="done"), USER_FLOW
    )
    flow = [e for e in rec.events if e["event_id"] == "f0"]
    assert [(e["event_type"], e["status"]) for e in flow] == [
        ("chain_start", "running"),
        ("chain_end", "completed"),
    ]
    assert all(e["agent_type"] == "flow" for e in flow)
    assert flow[0]["agent_name"] == "TwoCrewFlow"
    assert flow[0]["payload"]["inputs"] == {"q": 1}
    assert flow[1]["payload"]["outputs"] == {"output": "done"}
    assert flow[1]["latency_ms"] == 3000
    crews = [e for e in rec.events if e["agent_type"] == "crew"]
    assert {e["parent_event_id"] for e in crews} == {"f0"}
    assert not any(e["event_type"].startswith("method") for e in rec.events)


def test_flow_sets_session_status_once_at_the_end(mapper, rec):
    flow_run(mapper, 0)
    assert rec.status == [], "crews inside a flow must not set the session status"
    mapper.handle(ev("flow_finished", "f0e", started="f0"), USER_FLOW)
    assert rec.status == ["completed"]


def test_failed_flow_sets_session_status_failed_once(mapper, rec):
    flow_run(mapper, 0, second_fails=True)
    assert rec.status == []
    mapper.handle(
        ev("flow_failed", "f0e", started="f0", error=RuntimeError("boom")), USER_FLOW
    )
    assert rec.status == ["failed"]
    end = rec.events[-1]
    assert (end["event_id"], end["event_type"]) == ("f0", "chain_error")
    assert end["payload"]["error"] == "boom"


def test_standalone_crew_still_sets_session_status(mapper, rec):
    mapper.handle(ev("crew_kickoff_started", "c1"))
    mapper.handle(ev("crew_kickoff_completed", "c1e", started="c1"))
    assert rec.status == ["completed"]


def test_only_the_outermost_flow_sets_session_status(mapper, rec):
    mapper.handle(ev("flow_started", "outer", flow_name="Outer"), USER_FLOW)
    mapper.handle(ev("method_execution_started", "m", parent="outer"), USER_FLOW)
    # A flow kicked off from inside a method of the outer flow.
    mapper.handle(ev("flow_started", "inner", parent="m", flow_name="Inner"), USER_FLOW)
    mapper.handle(ev("flow_finished", "inner-e", parent="m", started="inner"))
    assert rec.status == [], "a nested flow must not set the session status"
    inner = [e for e in rec.events if e["event_id"] == "inner"]
    assert {e["parent_event_id"] for e in inner} == {"outer"}
    mapper.handle(ev("method_execution_finished", "m-e", parent="outer", started="m"))
    mapper.handle(ev("flow_finished", "outer-e", started="outer"), USER_FLOW)
    assert rec.status == ["completed"]


def test_crew_nested_in_a_tool_inside_a_flow_does_not_set_status(mapper, rec):
    mapper.handle(ev("flow_started", "f", flow_name="F"), USER_FLOW)
    mapper.handle(ev("crew_kickoff_started", "c", parent="f"))
    mapper.handle(ev("tool_usage_started", "u", parent="c", tool_name="delegate"))
    mapper.handle(ev("crew_kickoff_started", "n", parent="u", crew_name="inner"))
    mapper.handle(ev("crew_kickoff_failed", "n-e", parent="u", started="n"))
    mapper.handle(ev("tool_usage_finished", "u-e", parent="c", started="u"))
    mapper.handle(ev("crew_kickoff_completed", "c-e", parent="f", started="c"))
    assert rec.status == []
    mapper.handle(ev("flow_finished", "f-e", started="f"), USER_FLOW)
    assert rec.status == ["completed"]
    inner = [e for e in rec.events if e["event_id"] == "n"]
    assert {e["parent_event_id"] for e in inner} == {"u"}


def test_internal_flows_stay_hidden_and_never_set_status(mapper, rec):
    mapper.handle(ev("agent_execution_started", "a", agent_role="R"))
    mapper.handle(
        ev("flow_started", "x", parent="a", flow_name="AgentExecutor"), INTERNAL_FLOW
    )
    mapper.handle(ev("llm_call_started", "m", parent="x", model="gpt-4o"))
    mapper.handle(ev("llm_call_completed", "m-e", parent="x", started="m"))
    mapper.handle(ev("flow_finished", "x-e", parent="a", started="x"), INTERNAL_FLOW)
    assert {e["event_id"] for e in rec.events} == {"a", "m"}
    assert {e["parent_event_id"] for e in rec.events if e["event_id"] == "m"} == {"a"}
    assert rec.status == []


def test_paused_flow_is_forgotten_without_setting_status(mapper, rec):
    mapper.handle(ev("flow_started", "f", flow_name="F"), USER_FLOW)
    mapper.handle(ev("flow_paused", "f-p", started="f", method_name="ask"), USER_FLOW)
    assert rec.status == []
    assert [e["status"] for e in rec.events] == ["running"]
    assert (len(mapper._parents), len(mapper._shown), len(mapper._started_at)) == (
        0,
        0,
        0,
    )


def test_bookkeeping_stays_flat_across_many_flows(mapper, rec):
    for i in range(50):
        flow_run(mapper, i, second_fails=bool(i % 2))
        end = "flow_failed" if i % 2 else "flow_finished"
        mapper.handle(ev(end, f"f{i}e", started=f"f{i}", error="x"), USER_FLOW)
        assert (len(mapper._parents), len(mapper._shown), len(mapper._started_at)) == (
            0,
            0,
            0,
        )
    assert rec.status == ["completed", "failed"] * 25


def test_user_flow_that_suppresses_flow_events_is_still_shown(mapper, rec):
    mapper.handle(ev("flow_started", "f", flow_name="Quiet"), QUIET_USER_FLOW)
    mapper.handle(ev("crew_kickoff_started", "c", parent="f"))
    mapper.handle(ev("crew_kickoff_completed", "c-e", parent="f", started="c"))
    assert rec.status == []
    mapper.handle(ev("flow_finished", "f-e", started="f"), QUIET_USER_FLOW)
    assert rec.status == ["completed"]
    crew = [e for e in rec.events if e["event_id"] == "c"]
    assert {e["parent_event_id"] for e in crew} == {"f"}


def test_internal_marker_wins_over_suppress_flow_events(mapper, rec):
    loud_internal = _InternalFlow(suppress_flow_events=False)
    mapper.handle(ev("flow_started", "x", flow_name="AgentExecutor"), loud_internal)
    assert rec.events == []


def test_flow_source_without_the_marker_falls_back_to_suppress_flow_events(mapper, rec):
    """For CrewAI releases that predate ``is_crewai_internal``."""
    mapper.handle(
        ev("flow_started", "x", flow_name="AgentExecutor"),
        SimpleNamespace(suppress_flow_events=True),
    )
    mapper.handle(
        ev("flow_started", "f", flow_name="Mine"),
        SimpleNamespace(suppress_flow_events=False),
    )
    assert [e["event_id"] for e in rec.events] == ["f"]
