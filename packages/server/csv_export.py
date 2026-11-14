"""CSV serialization for session telemetry exports.

One row per event. Frequently analysed payload fields are flattened into
dedicated columns, and the complete payload is kept as JSON in
``payload_json`` so no information is lost.
"""

import csv
import io
import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Iterator, List, Optional

from pricing import calculate_cost

CSV_COLUMNS: List[str] = [
    "event_id",
    "parent_event_id",
    "session_id",
    "event_type",
    "agent_name",
    "agent_type",
    "status",
    "timestamp",
    "latency_ms",
    "model",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "tool_name",
    "error",
    "payload_json",
]

# Spreadsheet applications evaluate cells starting with these characters as
# formulas (CSV/formula injection, OWASP). Tab and carriage return are included
# because some applications strip them and then evaluate the remainder.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_.-]+")
_UNSAFE_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]+")


def sanitize_cell(value: Any) -> Any:
    """Neutralise text that a spreadsheet would interpret as a formula.

    Only strings are touched; numbers are written as-is so that numeric columns
    stay numeric.
    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return "" if value is None else str(value)


def event_to_row(event: Any) -> Dict[str, Any]:
    """Flatten an ``EventModel``-like object into a CSV row dict."""
    payload = event.payload if isinstance(event.payload, dict) else {}

    model = payload.get("model")
    model = model if isinstance(model, str) else None
    prompt_tokens = _as_int(payload.get("prompt_tokens"))
    completion_tokens = _as_int(payload.get("completion_tokens"))
    total_tokens = _as_int(payload.get("total_tokens"))
    if total_tokens is None and (
        prompt_tokens is not None or completion_tokens is not None
    ):
        total_tokens = (prompt_tokens or 0) + (completion_tokens or 0)

    cost_usd: Optional[float] = None
    if model and (prompt_tokens is not None or completion_tokens is not None):
        try:
            cost_usd = round(calculate_cost(model, prompt_tokens, completion_tokens), 8)
        except ValueError:
            # Negative token counts in a corrupted payload: leave cost empty.
            cost_usd = None

    tool_name = payload.get("tool_name")
    error = payload.get("error")

    return {
        "event_id": event.event_id,
        "parent_event_id": event.parent_event_id or "",
        "session_id": event.session_id,
        "event_type": event.event_type,
        "agent_name": event.agent_name,
        "agent_type": event.agent_type,
        "status": event.status,
        "timestamp": _format_timestamp(event.timestamp),
        "latency_ms": "" if event.latency_ms is None else event.latency_ms,
        "model": model or "",
        "prompt_tokens": "" if prompt_tokens is None else prompt_tokens,
        "completion_tokens": "" if completion_tokens is None else completion_tokens,
        "total_tokens": "" if total_tokens is None else total_tokens,
        "cost_usd": "" if cost_usd is None else cost_usd,
        "tool_name": tool_name if isinstance(tool_name, str) else "",
        "error": "" if error is None else str(error),
        "payload_json": json.dumps(
            event.payload, ensure_ascii=False, sort_keys=True, default=str
        ),
    }


def _write_row(row: Iterable[Any]) -> str:
    buffer = io.StringIO()
    # QUOTE_MINIMAL + "\r\n" (RFC 4180) quotes embedded commas, quotes and
    # newlines, which multi-line prompts and completions routinely contain.
    csv.writer(buffer, lineterminator="\r\n").writerow(row)
    return buffer.getvalue()


def header_line() -> str:
    return _write_row(CSV_COLUMNS)


def row_line(event: Any) -> str:
    row = event_to_row(event)
    return _write_row(sanitize_cell(row[column]) for column in CSV_COLUMNS)


def iter_csv(events: Iterable[Any], include_bom: bool = True) -> Iterator[str]:
    """Yield the CSV document line by line (header first).

    A UTF-8 byte-order mark is emitted by default so Excel detects the encoding;
    pandas and Google Sheets ignore it.
    """
    yield ("﻿" if include_bom else "") + header_line()
    for event in events:
        yield row_line(event)


def export_filename(session_name: Optional[str], session_id: str) -> str:
    """Build a header-safe ``<name>_<id8>.csv`` download filename."""
    safe_name = _UNSAFE_FILENAME_CHARS.sub("_", session_name or "").strip("._")
    safe_name = safe_name[:64] or "session"
    safe_id = _UNSAFE_ID_CHARS.sub("", session_id)[:8] or "export"
    return f"{safe_name}_{safe_id}.csv"
