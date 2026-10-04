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
