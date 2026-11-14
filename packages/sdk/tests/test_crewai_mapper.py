"""CrewAIEventMapper unit tests using lightweight fake events (no CrewAI)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from agentscope._pricing import calculate_cost
from agentscope.integrations.crewai import CrewAIEventMapper

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
