"""Reusable field and query-parameter validators shared by every endpoint.

Each later item (payments, requests, splits, settlements) builds its
endpoint-specific `validate_fields` on top of these primitives so the
precedence and ordering rules in R-1-067..077 are enforced the same way
everywhere.
"""
from __future__ import annotations

import re

from .errors import ApiError, malformed_request, validation_failed

HANDLE_RE = re.compile(r"^[a-z0-9_]{1,20}$")
_INT_RE = re.compile(r"^-?\d+$")
_MAX_IDEMPOTENCY_KEY_LEN = 255


def parse_amount(value, *, min_value: int | None = None, max_value: int | None = None) -> int:
    """R-1-031..033: integer count of minor units.

    1000, 1000.0 and 1e3 are all accepted (integral numeric value); a bool or
    string is rejected as 422, never 400 (R-1-069); a non-integral number is
    422. An optional range (e.g. R-1-134's 1..1_000_000_000 for payments) is
    checked here too, same code either way.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation_failed("amount must be a number")
    if isinstance(value, float):
        if not value.is_integer():
            raise validation_failed("amount must be an integral number of minor units")
        value = int(value)
    if min_value is not None and value < min_value:
        raise validation_failed(f"amount must be at least {min_value}")
    if max_value is not None and value > max_value:
        raise validation_failed(f"amount must be at most {max_value}")
    return value


def validate_note(body: dict, key: str = "note", *, max_length: int = 500) -> str:
    """R-1-069/070/136: note must be a string, verbatim, at most max_length
    Unicode code points. An **absent** key defaults to "" (never an error);
    a **present** key that is non-string — including explicit `null` — is
    422, which is why this takes the containing dict rather than a bare
    value: `body.get(key)` cannot tell "absent" apart from "present: null".
    """
    if key not in body:
        return ""
    value = body[key]
    if not isinstance(value, str):
        raise validation_failed(f"{key} must be a string")
    if len(value) > max_length:
        raise validation_failed(f"{key} must be at most {max_length} characters")
    return value


def validate_visibility(body: dict, key: str = "visibility", *, default: str = "public") -> str:
    """R-1-069/070: anything other than "public"/"private" is 422, including
    wrong type and an explicit `null` — but an absent key defaults
    (R-1-070), same absent-vs-null distinction as `validate_note`."""
    if key not in body:
        return default
    value = body[key]
    if value not in ("public", "private"):
        raise validation_failed('visibility must be "public" or "private"')
    return value


def validate_handle_syntax(value) -> str:
    """R-1-077: non-string handle is 400; syntactically invalid handle is 422."""
    if not isinstance(value, str):
        raise malformed_request("handle must be a string")
    if not HANDLE_RE.match(value):
        raise validation_failed("handle must match ^[a-z0-9_]{1,20}$")
    return value


def validate_idempotency_key(raw: str | None) -> str:
    """R-1-062, R-1-072: presence is a 400, length is a 422."""
    from .errors import missing_idempotency_key

    if not raw:
        raise missing_idempotency_key()
    if len(raw) > _MAX_IDEMPOTENCY_KEY_LEN:
        raise validation_failed("Idempotency-Key must be at most 255 characters")
    return raw


def parse_query_int(raw: str | None, *, min_value: int | None, max_value: int | None,
                     field_name: str, default: int | None = None) -> int | None:
    """R-1-071, R-1-073, R-1-074: strict plain-decimal query integers.

    `1e9`, `4.0`, `+4`, ` 4`, `0x4` and an empty string are 422 regardless of
    their numeric value; a leading `-` is only accepted when min_value allows
    negative values.
    """
    if raw is None:
        return default
    if not _INT_RE.match(raw):
        raise validation_failed(f"{field_name} must be a plain decimal integer")
    value = int(raw)
    if min_value is not None and value < min_value:
        raise validation_failed(f"{field_name} must be at least {min_value}")
    if max_value is not None and value > max_value:
        raise validation_failed(f"{field_name} must be at most {max_value}")
    return value


def parse_limit(raw: str | None, default: int = 50) -> int:
    return parse_query_int(raw, min_value=1, max_value=200, field_name="limit", default=default)


def parse_offset(raw: str | None, default: int = 0) -> int:
    return parse_query_int(raw, min_value=0, max_value=None, field_name="offset", default=default)
