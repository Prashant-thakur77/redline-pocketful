"""Invariant checks shared between `POST /_test/reset` and
`POST /_test/import` (R-1-204a).

Both doors restore the same kind of state — a fixture is just a smaller,
caller-authored version of what import restores wholesale — so they must
enforce the same stated invariants, not merely their own envelope/shape
checks. One call site per invariant here means a later stage's new
invariant (R-2-024, R-2-028, R-3-023, ...) is one addition, not two.
"""
from __future__ import annotations

from .errors import validation_failed


def check_nonnegative_balances(wallets: dict) -> None:
    """R-1-002/R-1-045: no wallet balance is ever negative, not even
    transiently — true of a balance arriving via a seeded fixture and
    equally true of one arriving via an imported state document."""
    for user_id, balance in wallets.items():
        if balance < 0:
            raise validation_failed(f"wallet balance for {user_id} must not be negative")


def check_holds_within_balance(wallets: dict, authorizations: dict, now: float) -> None:
    """R-2-024: a user whose seeded open, unexpired holds sum to more than
    their balance is rejected — same shape as check_nonnegative_balances,
    just computed on R-2-004's definition of `held` instead of a raw
    field. `now` is taken at reset/import time: a seeded `open`
    authorization already past its expiry holds nothing here either
    (R-2-026), matching the read-time rule it's checked against later."""
    from .holds import is_open, remaining_amount

    held: dict[str, int] = {}
    for a in authorizations.values():
        if is_open(a, now):
            held[a["from_user_id"]] = held.get(a["from_user_id"], 0) + remaining_amount(a)

    for user_id, total_held in held.items():
        if total_held > wallets.get(user_id, 0):
            raise validation_failed(f"seeded open holds for {user_id} exceed balance")
