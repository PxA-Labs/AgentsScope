"""Unit tests for the CSV serializer (no database or HTTP involved)."""

import csv
import io
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from csv_export import (
    CSV_COLUMNS,
    event_to_row,
    export_filename,
    iter_csv,
    sanitize_cell,
)
from pricing import calculate_cost

NOW = datetime(2026, 11, 15, 12, 30, 0, tzinfo=timezone.utc)


def make_event(**overrides):
    base = dict(
        event_id="evt-1",
        parent_event_id=None,
        session_id="sess-1",
        event_type="llm_end",
        agent_name="ChatOpenAI",
        agent_type="llm",
        status="completed",
        timestamp=NOW,
        latency_ms=420,
        payload={
            "model": "gpt-4o",
            "prompts": ["Hello"],
            "completion": "Hi there",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def parse(document: str):
    return list(csv.DictReader(io.StringIO(document.lstrip("\ufeff"))))


def test_header_matches_documented_columns():
    lines = list(iter_csv([], include_bom=False))
    assert lines == [",".join(CSV_COLUMNS) + "\r\n"]


def test_llm_event_is_flattened_with_cost():
    row = event_to_row(make_event())
    assert row["model"] == "gpt-4o"
    assert row["prompt_tokens"] == 10
    assert row["completion_tokens"] == 5
    assert row["total_tokens"] == 15
    assert row["cost_usd"] == pytest.approx(calculate_cost("gpt-4o", 10, 5))
    assert row["cost_usd"] > 0
    assert row["timestamp"] == "2026-11-15T12:30:00+00:00"
    assert row["parent_event_id"] == ""


def test_total_tokens_derived_when_missing():
    event = make_event(payload={"model": "gpt-4o", "prompt_tokens": 7})
    row = event_to_row(event)
    assert row["total_tokens"] == 7
    assert row["completion_tokens"] == ""


def test_unknown_model_has_zero_cost_and_missing_usage_has_blank_cost():
    priced = event_to_row(
        make_event(payload={"model": "not-a-real-model", "prompt_tokens": 3})
    )
    assert priced["cost_usd"] == 0.0
    unpriced = event_to_row(make_event(payload={"model": "gpt-4o"}))
    assert unpriced["cost_usd"] == ""


def test_negative_token_counts_do_not_crash_export():
    row = event_to_row(make_event(payload={"model": "gpt-4o", "prompt_tokens": -5}))
    assert row["cost_usd"] == ""


def test_tool_event_columns():
    event = make_event(
        event_type="tool_error",
        agent_type="tool",
        status="error",
        latency_ms=None,
        payload={"tool_name": "calculator", "input": "1/0", "error": "ZeroDivision"},
    )
    row = event_to_row(event)
    assert row["tool_name"] == "calculator"
    assert row["error"] == "ZeroDivision"
    assert row["model"] == ""
    assert row["latency_ms"] == ""
    assert row["cost_usd"] == ""


def test_payload_json_round_trips_and_handles_non_dict_payload():
    event = make_event()
    row = event_to_row(event)
    assert json.loads(row["payload_json"]) == event.payload

    none_row = event_to_row(make_event(payload=None))
    assert none_row["payload_json"] == "null"
    assert none_row["model"] == ""


@pytest.mark.parametrize(
    "value", ['=HYPERLINK("http://x")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rx"]
)
def test_formula_prefixes_are_neutralised(value):
    assert sanitize_cell(value) == "'" + value


@pytest.mark.parametrize("value", ["hello", "", "1+1", 42, -3, 0.5, None])
def test_safe_values_are_unchanged(value):
    assert sanitize_cell(value) == value


def test_formula_injection_in_full_document():
    event = make_event(
        agent_name="=cmd|' /C calc'!A0",
        payload={"tool_name": "@evil", "error": "-boom"},
    )
    (row,) = parse("".join(iter_csv([event])))
    assert row["agent_name"] == "'=cmd|' /C calc'!A0"
    assert row["tool_name"] == "'@evil"
    assert row["error"] == "'-boom"


def test_multiline_and_unicode_text_survive_round_trip():
    prompt = 'Line one, with comma\nLine "two"\r\nemoji 🚀 and ünïcode'
    event = make_event(payload={"model": "gpt-4o", "prompts": [prompt]})
    document = "".join(iter_csv([event]))
    assert document.startswith("\ufeff")
    (row,) = parse(document)
    assert json.loads(row["payload_json"])["prompts"] == [prompt]
    assert set(row) == set(CSV_COLUMNS)


@pytest.mark.parametrize(
    "name,session_id,expected",
    [
        ("My Run", "9b1deb4d-3b7d", "My_Run_9b1deb4d.csv"),
        ('evil"\r\nX-Header: 1', "abc", "evil_X-Header_1_abc.csv"),
        ("", "abcdef123456", "session_abcdef12.csv"),
        (None, "../../etc", "session_etc.csv"),
        ("../../passwd", "id", "passwd_id.csv"),
    ],
)
def test_export_filename_is_header_safe(name, session_id, expected):
    assert export_filename(name, session_id) == expected
