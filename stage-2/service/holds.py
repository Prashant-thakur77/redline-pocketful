"""The derived holds model (R-2-001..005).

`held` and `available` are never stored — both are computed from each
authorization's own `expires_at` on every read. A stored "held" counter
would be a second source of truth for money (the thing that burned
stage 1 whenever a value could be recomputed two different ways), and a
sweeper thread that periodically flips `status` to `expired` is wrong at
instant granularity (R-2-030: expiry must be exact and read-driven, with
no write required for the read to be correct).
"""
from __future__ import annotations

import time


def remaining_amount(authorization: dict) -> int:
    return authorization["amount"] - authorization.get("captured_amount", 0)


def effective_status(authorization: dict, now: float) -> str:
    """R-2-030: an authorization whose expires_at is at or before now reads
    as expired regardless of its stored status — but only a stored `open`
    can ever become `expired` this way; a captured/voided hold is already
    closed and stays whatever it is."""
    if authorization["status"] == "open" and authorization["expires_at"] <= now:
        return "expired"
    return authorization["status"]


def is_open(authorization: dict, now: float) -> bool:
    return effective_status(authorization, now) == "open"


def held_for(store, user_id: str, now: float | None = None) -> int:
    """R-2-004: sum of remaining_amount over the caller's open, unexpired
    authorizations where the caller is the payer (from_user_id) — never
    counts an authorization where the caller is the receiver."""
    if now is None:
        now = time.time()
    return sum(
        remaining_amount(a) for a in store.authorizations.values()
        if a["from_user_id"] == user_id and is_open(a, now)
    )


def available_for(store, user_id: str, now: float | None = None) -> int:
    """R-2-002: available = total - held, never negative."""
    total = store.wallets.get(user_id, 0)
    return total - held_for(store, user_id, now)
