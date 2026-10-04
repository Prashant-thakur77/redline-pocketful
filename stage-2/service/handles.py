"""Handle derivation from an email's local part (R-1-036).

Order matters: substitute per character first, over the *whole* local
part, then truncate to 20 — truncating first would make a 21+ character
local part collide differently than the spec intends, and collapsing
runs of substituted characters (instead of one `_` per character) would
make `a..b` and `a_b` indistinguishable from `a.b`.
"""
from __future__ import annotations

import re

_INVALID_HANDLE_CHAR = re.compile(r"[^a-z0-9_]")
_MAX_HANDLE_LEN = 20


def derive_handle(email: str) -> str:
    local = email.split("@", 1)[0]
    substituted = _INVALID_HANDLE_CHAR.sub("_", local.lower())
    return substituted[:_MAX_HANDLE_LEN]
