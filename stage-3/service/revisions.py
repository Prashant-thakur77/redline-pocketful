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


def select_revision_as_of(revisions: list[dict], as_of_epoch: float) -> dict | None:
    """R-3-022/023: the revision in effect at `as_of` is whichever has the
    HIGHEST revision number among those whose `effective_at <= as_of` —
    a later-recorded, backdated correction overrides an earlier
    revision's amount for every `as_of` at or after its own
    `effective_at`, regardless of which revision's `effective_at` is
    chronologically later. None qualifying means the payment hasn't
    happened yet in this view."""
    best = None
    for rev in revisions:
        if parse_rfc3339(rev["effective_at"]) <= as_of_epoch:
            if best is None or rev["revision"] > best["revision"]:
                best = rev
    return best


def balance_as_of(opening_balances: dict, payments: dict, payment_revisions: dict,
                   user_id: str, as_of_epoch: float) -> int:
    """R-3-016/021..024: the opening balance plus the net effect of every
    payment this user is party to, each contributing through whichever
    of its own revisions is selected at `as_of` (or nothing, if none
    qualify yet) — never the payment's current, fully-corrected amount
    directly."""
    total = opening_balances.get(user_id, 0)
    for p in payments.values():
        is_from = p["from_user_id"] == user_id
        is_to = p["to_user_id"] == user_id
        if not (is_from or is_to):
            continue
        rev = select_revision_as_of(payment_revisions.get(p["id"], []), as_of_epoch)
        if rev is None:
            continue
        total += -rev["amount"] if is_from else rev["amount"]
    return total


def validate_payment_history_nonnegative(wallets: dict, payments: dict) -> None:
    """R-3-018/R-3-002/R-3-016: replaying the seeded payments in R-3-019
    order from the opening balance must never drive a wallet negative at
    any point — including the opening instant itself, before any
    seeded payment is replayed. A receiver whose ending balance is low
    but who was seeded as having received more than that implies a
    negative opening balance, and `as_of` before the earliest payment
    (R-3-024) would expose exactly that negative figure — planner's
    ruling (adversary BREACH 0dfd763): this must be 422 from reset, not
    merely checked after each forward step."""
    running = compute_opening_balances(wallets, payments)
    if any(bal < 0 for bal in running.values()):
        raise validation_failed("seeded payment history implies a negative opening balance")
    for p in ordered_by_time_then_id(payments):
        running[p["from_user_id"]] -= p["amount"]
        running[p["to_user_id"]] += p["amount"]
        if running[p["from_user_id"]] < 0 or running[p["to_user_id"]] < 0:
            raise validation_failed("seeded payment history implies a negative balance at some point")
