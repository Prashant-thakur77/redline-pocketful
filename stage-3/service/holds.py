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

from .json_utils import parse_rfc3339


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


def remaining_at(authorization: dict, as_of_epoch: float, known_at_epoch: float | None = None) -> int:
    """R-3-110..115: what this one authorization contributed to `held` as
    of `as_of_epoch`, as known by `known_at_epoch` -- never the
    current/live state. Four ways a hold stops contributing, in the
    order checked: it hadn't been opened yet, by effective time
    (R-3-110); its creation is not yet KNOWN at known_at at all (R-3-113
    -- "once an authorization's creation is known, its expiry deadline
    is known too" implies the inverse: unknown creation means nothing
    about it, including its later expiry, is knowable yet, so it
    contributes nothing to this view); it was closed (captured-final or
    voided) by a RECORDED event that is both at-or-before as_of AND
    itself known by known_at (R-3-111/112 -- release needs an event, and
    that event is only known at its own server-assigned time, R-3-112);
    or its clock deadline had passed by as_of regardless of any recorded
    event (R-3-112/113/114 -- expiry itself needs no event beyond
    creation being known, so it is not separately gated by known_at).
    Otherwise, the amount already captured by recorded events that are
    both at-or-before as_of and known by known_at is subtracted
    (R-3-111: each nonfinal capture reduces the hold at its OWN instant,
    not retroactively, and is only visible once that instant is known).
    known_at_epoch=None means no restriction from that axis, the same
    convention `revisions.select_revision` uses."""
    created_epoch = parse_rfc3339(authorization["created_at"])
    if as_of_epoch < created_epoch:
        return 0
    if known_at_epoch is not None and created_epoch > known_at_epoch:
        return 0

    closed_at = authorization.get("closed_at")
    if closed_at is not None:
        closed_epoch = parse_rfc3339(closed_at)
        if closed_epoch <= as_of_epoch and (known_at_epoch is None or closed_epoch <= known_at_epoch):
            return 0
    if authorization["expires_at"] <= as_of_epoch:
        return 0

    captured_before = sum(
        event["amount"] for event in authorization.get("capture_events", [])
        if parse_rfc3339(event["at"]) <= as_of_epoch
        and (known_at_epoch is None or parse_rfc3339(event["at"]) <= known_at_epoch)
    )
    return authorization["amount"] - captured_before


def held_at(store, user_id: str, as_of_epoch: float, known_at_epoch: float | None = None) -> int:
    """R-3-110: the historical/bitemporal twin of `held_for`, using
    `remaining_at` per authorization instead of the live/current
    remainder."""
    return sum(
        remaining_at(a, as_of_epoch, known_at_epoch) for a in store.authorizations.values()
        if a["from_user_id"] == user_id
    )
