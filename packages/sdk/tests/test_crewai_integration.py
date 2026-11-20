"""AgentScopeCrewAIListener against a real CrewAI crew (no network, no LLM).

A scripted BaseLLM subclass returns ReAct-formatted responses and emits the
same LLM call events CrewAI's built-in LLM classes emit, so the crew, task,
agent, tool and LLM events all come from CrewAI itself.
"""

import os

import pytest

for _key, _value in {
    "CREWAI_DISABLE_TELEMETRY": "true",
    "OTEL_SDK_DISABLED": "true",
    "CREWAI_TRACING_ENABLED": "false",
}.items():
    os.environ.setdefault(_key, _value)

crewai = pytest.importorskip("crewai")

from crewai import Agent, Crew, Process, Task  # noqa: E402
from crewai.events import crewai_event_bus  # noqa: E402
from crewai.events.types.llm_events import LLMCallType  # noqa: E402
from crewai.llms.base_llm import BaseLLM  # noqa: E402
from crewai.tools import tool  # noqa: E402

from agentscope_trace.integrations.crewai import (  # noqa: E402
    AgentScopeCrewAIListener,
    instrument_crewai,
)


class ScriptedLLM(BaseLLM):
    def __init__(self, script, fail=False):
        super().__init__(model="gpt-4o-mini")
        self._script = list(script)
        self._fail = fail

    def supports_function_calling(self):
        return False

    def call(
        self,
        messages,
        tools=None,
        callbacks=None,
        available_functions=None,
        from_task=None,
        from_agent=None,
        response_model=None,
    ):
        self._emit_call_started_event(
            messages=messages, from_task=from_task, from_agent=from_agent
        )
        if self._fail:
            self._emit_call_failed_event(
                error="provider unavailable", from_task=from_task, from_agent=from_agent
            )
            raise RuntimeError("provider unavailable")
        response = self._script.pop(0)
        self._emit_call_completed_event(
            response=response,
            call_type=LLMCallType.LLM_CALL,
            from_task=from_task,
            from_agent=from_agent,
            messages=messages,
            usage={"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        )
        return response


@tool("lookup")
def lookup(q: str) -> str:
    """Look up a fact."""
    return f"fact about {q}"


class Recorder:
    def __init__(self):
        self.events = []
        self.status = []

    def emit(self, event):
        self.events.append(event)

    def patch_session_status(self, status):
        self.status.append(status)

    def stop(self):
        pass


def research_crew():
    researcher = Agent(
        role="Researcher",
        goal="find facts",
        backstory="b",
        tools=[lookup],
        llm=ScriptedLLM(
            [
                'Thought: use the tool\nAction: lookup\nAction Input: {"q": "paris"}',
                "Thought: done\nFinal Answer: Paris is the capital.",
            ]
        ),
    )
    writer = Agent(
        role="Writer",
        goal="write",
        backstory="b",
        llm=ScriptedLLM(["Thought: done\nFinal Answer: A short article."]),
    )
    return Crew(
        name="research-crew",
        agents=[researcher, writer],
        tasks=[
            Task(
                description="Research Paris", expected_output="facts", agent=researcher
            ),
            Task(description="Write article", expected_output="article", agent=writer),
        ],
        process=Process.sequential,
    )


@pytest.fixture
def recorder():
    rec = Recorder()
    listener = AgentScopeCrewAIListener(client=rec)
    yield rec
    listener.close()


def run(crew):
    try:
        return crew.kickoff()
    finally:
        crewai_event_bus.flush()


def nodes(rec):
    """Final state per node: the last event for each event_id."""
    final = {}
    for e in rec.events:
        final[e["event_id"]] = e
    return final


def test_crew_produces_full_dag(recorder):
    result = run(research_crew())
    assert result.raw == "A short article."

    final = nodes(recorder)
    by_name = {}
    for node in final.values():
        by_name.setdefault((node["agent_type"], node["agent_name"]), []).append(node)

    (crew,) = by_name[("crew", "research-crew")]
    tasks = {n: by_name[("task", n)][0] for n in ("Research Paris", "Write article")}
    researcher = by_name[("agent", "Researcher")][0]
    writer = by_name[("agent", "Writer")][0]
    (tool_node,) = by_name[("tool", "lookup")]
    llms = by_name[("llm", "gpt-4o-mini")]

    assert crew["parent_event_id"] is None
    assert all(t["parent_event_id"] == crew["event_id"] for t in tasks.values())
    assert researcher["parent_event_id"] == tasks["Research Paris"]["event_id"]
    assert writer["parent_event_id"] == tasks["Write article"]["event_id"]
    assert tool_node["parent_event_id"] == researcher["event_id"]
    assert len(llms) == 3
    assert sum(n["parent_event_id"] == researcher["event_id"] for n in llms) == 2
    assert sum(n["parent_event_id"] == writer["event_id"] for n in llms) == 1

    # Every node was opened and closed with the same event_id.
    assert all(n["status"] == "completed" for n in final.values())
    starts = [e for e in recorder.events if e["status"] == "running"]
    assert {e["event_id"] for e in starts} == set(final)

    assert tool_node["payload"]["input"] == '{"q": "paris"}'
    assert tool_node["payload"]["output"] == "fact about paris"
    assert all(n["payload"]["total_tokens"] == 60 for n in llms)
    assert all(n["payload"]["cost_usd"] > 0 for n in llms)
    assert crew["payload"]["outputs"]["output"] == "A short article."
    assert recorder.status == ["completed"]


def test_llm_failure_marks_nodes_and_session_failed(recorder):
    agent = Agent(
        role="Flaky",
        goal="g",
        backstory="b",
        llm=ScriptedLLM([], fail=True),
        max_retry_limit=0,
    )
    crew = Crew(
        agents=[agent], tasks=[Task(description="d", expected_output="o", agent=agent)]
    )
    with pytest.raises(RuntimeError, match="provider unavailable"):
        run(crew)

    final = nodes(recorder)
    statuses = {(n["agent_type"], n["status"]) for n in final.values()}
    assert statuses == {
        ("crew", "error"),
        ("task", "error"),
        ("agent", "error"),
        ("llm", "error"),
    }
    llm = next(n for n in final.values() if n["agent_type"] == "llm")
    assert llm["event_type"] == "llm_error"
    assert llm["payload"]["error"] == "provider unavailable"
    assert recorder.status == ["failed"]


def test_close_unsubscribes_from_event_bus():
    rec = Recorder()
    listener = instrument_crewai(client=rec)
    listener.close()
    run(research_crew())
    assert rec.events == []


def test_close_delivers_events_still_pending_on_the_bus():
    """Events emitted outside kickoff() (which flushes on its own) must not be
    lost when close() is called immediately afterwards."""
    from datetime import datetime

    from crewai.events.types.tool_usage_events import (
        ToolUsageFinishedEvent,
        ToolUsageStartedEvent,
    )

    rec = Recorder()
    listener = AgentScopeCrewAIListener(client=rec)
    common = {"tool_args": {}, "tool_class": "X", "agent_key": "k"}
    for i in range(100):
        # Balanced start/finish pairs keep CrewAI's event scope stack empty.
        crewai_event_bus.emit(None, ToolUsageStartedEvent(tool_name=f"t{i}", **common))
        now = datetime.now()
        crewai_event_bus.emit(
            None,
            ToolUsageFinishedEvent(
                tool_name=f"t{i}",
                started_at=now,
                finished_at=now,
                output="ok",
                **common,
            ),
        )
    listener.close()
    assert len(rec.events) == 200


def test_bookkeeping_stays_flat_across_many_kickoffs():
    rec = Recorder()
    listener = AgentScopeCrewAIListener(client=rec)
    try:
        sizes = []
        for _ in range(10):
            run(research_crew())
            m = listener.mapper
            sizes.append((len(m._parents), len(m._shown), len(m._started_at)))
    finally:
        listener.close()
    assert len(set(sizes)) == 1, sizes
    assert sizes[-1] == (0, 0, 0), sizes


def test_standalone_agent_kickoff_is_recorded(recorder):
    agent = Agent(
        role="Solo",
        goal="answer",
        backstory="b",
        tools=[lookup],
        llm=ScriptedLLM(
            [
                'Thought: use the tool\nAction: lookup\nAction Input: {"q": "paris"}',
                "Thought: done\nFinal Answer: Paris.",
            ]
        ),
    )
    try:
        result = agent.kickoff("What is the capital of France?")
    finally:
        crewai_event_bus.flush()
    assert result.raw == "Paris."

    final = nodes(recorder)
    (solo,) = [n for n in final.values() if n["agent_type"] == "agent"]
    assert solo["agent_name"] == "Solo" and solo["parent_event_id"] is None
    assert solo["status"] == "completed"
    assert solo["payload"]["outputs"]["output"] == "Paris."
    start = next(e for e in recorder.events if e["event_id"] == solo["event_id"])
    assert "What is the capital of France?" in str(start["payload"]["inputs"])
    children = [n for n in final.values() if n["agent_type"] in ("tool", "llm")]
    assert len(children) == 3
    assert all(n["parent_event_id"] == solo["event_id"] for n in children)
    assert all(n["status"] == "completed" for n in children)
