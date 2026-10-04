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


def parse_amount(value) -> int:
    """R-1-031..033: integer count of minor units.

    1000, 1000.0 and 1e3 are all accepted (integral numeric value); a bool or
    string is rejected as 422, never 400 (R-1-069); a non-integral number is
    422.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise validation_failed("amount must be a number")
    if isinstance(value, float):
        if not value.is_integer():
            raise validation_failed("amount must be an integral number of minor units")
        value = int(value)
    return value


def validate_note(value, *, required: bool = False, max_length: int = 500):
    """note must be a string (R-1-069); null or any non-string is 422."""
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise validation_failed("note must be a string")
    if len(value) > max_length:
        raise validation_failed(f"note must be at most {max_length} characters")
    return value


def validate_visibility(value, *, default: str = "public"):
    """Anything other than "public"/"private" is 422, including wrong type (R-1-069)."""
    if value is None:
        return default
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
