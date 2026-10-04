"""Strict JSON parsing and RFC 3339 timestamps (R-1-004, R-1-020, R-1-021)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from .errors import malformed_request


def parse_json_object(raw: bytes) -> dict:
    """Decode a request body as UTF-8 JSON and require a top-level object.

    Raises malformed_request (400) for anything else, per R-1-061.
    """
    if raw is None or raw == b"":
        return {}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise malformed_request("request body is not valid UTF-8")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        raise malformed_request("request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise malformed_request("request body must be a JSON object")
    return parsed


def dumps(obj) -> bytes:
    """Serialize a response body. Money is always an int, never a float."""
    return json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")


def now_rfc3339() -> str:
    """Current instant as RFC 3339 with an explicit numeric offset (R-1-021)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
