"""Strict JSON parsing and RFC 3339 timestamps (R-1-004, R-1-020, R-1-021)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .errors import malformed_request


def _reject_non_finite(token: str):
    raise ValueError(f"non-finite number literal {token!r} is not valid JSON")


def parse_json_object(raw: bytes) -> dict:
    """Decode a request body as UTF-8 JSON and require a top-level object.

    Raises malformed_request (400) for anything else, per R-1-061.
    `NaN`/`Infinity`/`-Infinity` are a Python json extension, not strict
    JSON, and would make stored-body equality non-reflexive (NaN != NaN)
    for idempotency (R-1-106) — rejected here so one never enters a
    stored body in the first place.
    """
    if raw is None or raw == b"":
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise malformed_request("request body is not valid UTF-8")
    try:
        parsed = json.loads(text, parse_constant=_reject_non_finite)
    except (json.JSONDecodeError, ValueError):
        raise malformed_request("request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise malformed_request("request body must be a JSON object")
    return parsed


def dumps(obj) -> bytes:
    """Serialize a response body. Money is always an int, never a float."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")


def now_rfc3339() -> str:
    """Current instant as RFC 3339 with an explicit numeric offset
    (R-1-021). Microsecond precision, not seconds: stage 3's `as_of`
    effective-time boundary (R-3-022/023) compares a server-recorded
    `created_at`/`effective_at` against a caller-supplied instant that
    routinely carries full microsecond precision (`datetime.now(...)
    .isoformat()`) — truncating our own side to whole seconds can make a
    payment's own effective_at round DOWN past an as_of instant that
    was captured a fraction of a second before it in real time, wrongly
    including a payment an as_of query was meant to exclude."""
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def parse_rfc3339(value: str) -> float:
    """Parse an RFC 3339 timestamp (accepting a trailing `Z`) to epoch
    seconds, for cheap `expires_at` comparisons (R-2-030). Raises
    ValueError on anything unparseable — the caller decides the error
    code, since the same parser serves both request fields (422) and
    seeded fixture fields (422 from a different endpoint)."""
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        raise ValueError("timestamp must carry an explicit offset")
    return dt.timestamp()


def epoch_to_rfc3339(epoch_seconds: float) -> str:
    """The inverse of `parse_rfc3339`, for echoing a stored `expires_at`
    back out with the same explicit-offset convention as every other
    timestamp (R-1-021)."""
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat(timespec="seconds")
