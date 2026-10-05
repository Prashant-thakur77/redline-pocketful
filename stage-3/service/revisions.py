"""Payment revision history (R-3-003, R-3-004, R-3-015, R-3-016, R-3-101).

Revision 1 is never lazily materialized on first correction — every
payment that exists has one, from the instant it exists, regardless of
which of the four creation paths (direct, request-pay, settlement member,
capture) or which bulk path (seeded fixture, import) produced it. This
module is the one place that builds a revision 1 record and the one
place that derives a fixture's opening balances, so every caller uses
the same shape.
"""
from __future__ import annotations

from .errors import validation_failed
from .json_utils import parse_rfc3339


def make_revision_1(amount: int, instant: str) -> dict:
    """A payment's first, original revision: `effective_at == recorded_at
    == instant` (R-3-015), `reason` empty — it was never a correction."""
    return {"revision": 1, "amount": amount, "effective_at": instant, "recorded_at": instant, "reason": ""}


def seed_revisions(payments: dict) -> dict[str, list[dict]]:
    """One revision 1 per payment, derived from each payment's own
    `created_at` — used identically for a fixture's seeded payments and
    for every payment an import carries across from a service that
    predates this revision model (R-3-003's "not synthesised lazily"
    trap applies the same way to both: every payment that EXISTS gets a
    revision 1, however it came to exist)."""
    return {pid: [make_revision_1(p["amount"], p["created_at"])] for pid, p in payments.items()}


def compute_opening_balances(wallets: dict, payments: dict) -> dict[str, int]:
    """R-3-016: a wallet's opening balance is its seeded ending balance
    minus the net effect of the payments that produced it."""
    opening = dict(wallets)
    for p in payments.values():
        opening[p["from_user_id"]] += p["amount"]
        opening[p["to_user_id"]] -= p["amount"]
    return opening


def ordered_by_time_then_id(payments: dict) -> list[dict]:
    """R-3-019: the deterministic tie-break — chronological by
    `created_at`, ties broken by payment id ascending."""
    return sorted(payments.values(), key=lambda p: (parse_rfc3339(p["created_at"]), p["id"]))


def validate_payment_history_nonnegative(wallets: dict, payments: dict) -> None:
    """R-3-018: replaying the seeded payments in R-3-019 order from the
    opening balance must never drive a wallet negative at any point."""
    running = compute_opening_balances(wallets, payments)
    for p in ordered_by_time_then_id(payments):
        running[p["from_user_id"]] -= p["amount"]
        running[p["to_user_id"]] += p["amount"]
        if running[p["from_user_id"]] < 0 or running[p["to_user_id"]] < 0:
            raise validation_failed("seeded payment history implies a negative balance at some point")
