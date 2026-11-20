"""Edge cases of the AutoGen run tracer's state machine (no AutoGen needed)."""

from types import SimpleNamespace

from agentscope_trace.integrations.autogen import _Emitter, _RunState


class Recorder:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


def msg(kind, source, content="", **fields):
    cls = type(kind, (), {})
    item = cls()
    item.source = source
    item.content = content
    item.models_usage = fields.pop("models_usage", None)
    for k, v in fields.items():
        setattr(item, k, v)
    return item


def new_state():
    rec = Recorder()
    state = _RunState(_Emitter(rec), "team")
    state.start("task")
    return rec, state


def test_task_message_and_streaming_chunks_create_no_turns():
    rec, state = new_state()
    state.observe(msg("TextMessage", "user", "the task"))
    state.observe(msg("ModelClientStreamingChunkEvent", "writer", "tok"))
    state.finish(None)
    assert [e["agent_type"] for e in rec.events] == ["team", "team"]


def test_an_agents_events_and_its_message_form_one_turn():
    rec, state = new_state()
    state.observe(msg("ThoughtEvent", "a", "thinking"))
    state.observe(msg("TextMessage", "a", "answer"))
    state.observe(msg("TextMessage", "b", "reply"))
    state.finish(None)
    turns = [
        e for e in rec.events if e["agent_type"] == "agent" and e["status"] != "running"
    ]
    assert [t["agent_name"] for t in turns] == ["a", "b"]
    assert turns[0]["payload"]["outputs"]["output"] == "answer"
    assert turns[0]["payload"]["outputs"]["thought"] == "thinking"


def test_handoff_is_recorded_on_the_turn():
    rec, state = new_state()
    state.observe(msg("HandoffMessage", "triage", "to billing", target="billing"))
    state.finish(None)
    turn = [e for e in rec.events if e["agent_type"] == "agent"][-1]
    assert turn["payload"]["outputs"]["handoff"] == "billing"


def test_unmatched_tool_result_is_ignored_and_pending_tools_close_as_errors():
    rec, state = new_state()
    call = SimpleNamespace(id="c1", name="search", arguments='{"q": 1}')
    state.observe(msg("ToolCallRequestEvent", "a", [call]))
    state.observe(
        msg(
            "ToolCallExecutionEvent",
            "a",
            [
                SimpleNamespace(
                    call_id="other", content="x", name="search", is_error=False
                )
            ],
        )
    )
    state.finish(None)
    tool = [e for e in rec.events if e["agent_type"] == "tool"][-1]
    assert tool["event_type"] == "tool_error"
    assert tool["payload"]["error"] == "run finished before the tool returned"


def test_emitter_swallows_client_errors():
    class Broken:
        def emit(self, event):
            raise RuntimeError("down")

    _Emitter(Broken()).emit("id", "chain_start", "n", "team", "running", {}, None)


def test_each_response_by_the_same_agent_is_its_own_turn():
    rec, state = new_state()
    state.observe(msg("TextMessage", "solo", "first"))
    state.observe(msg("ToolCallRequestEvent", "solo", []))
    state.observe(msg("ToolCallSummaryMessage", "solo", "second"))
    state.observe(msg("TextMessage", "solo", "third"))
    state.finish(None)
    turns = [
        e for e in rec.events if e["agent_type"] == "agent" and e["status"] != "running"
    ]
    assert [t["payload"]["outputs"]["output"] for t in turns] == [
        "first",
        "second",
        "third",
    ]
    assert len({t["event_id"] for t in turns}) == 3
