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
    happened yet in this view.

    A correction (R-3-053) may set `effective_at` earlier than the
    payment's own revision 1 — "historical" backdating, deliberately
    exercised by the storm hook. That must never let the payment appear
    to have happened before it was ever created: revision 1's own
    `effective_at` is the payment's true existence boundary, so an
    `as_of` before it disqualifies every revision, including a
    correction that individually "qualifies" by its own effective_at."""
    if not revisions or as_of_epoch < parse_rfc3339(revisions[0]["effective_at"]):
        return None
    best = None
    for rev in revisions:
        if parse_rfc3339(rev["effective_at"]) <= as_of_epoch:
            if best is None or rev["revision"] > best["revision"]:
                best = rev
    return best


def select_known_revision(revisions: list[dict], known_at_epoch: float) -> dict | None:
    """R-3-071/077: the latest (highest revision number) revision RECORDED
    at or before `known_at` — selection by `recorded_at`, never
    `effective_at`. None qualifying (the payment's own revision 1 was
    itself recorded after `known_at`) means the payment is excluded from
    the view ENTIRELY, not zeroed — the caller must treat `None` the same
    way `select_revision_as_of` returning `None` is treated, by skipping
    the payment outright, never by contributing a zero delta for it."""
    best = None
    for rev in revisions:
        if parse_rfc3339(rev["recorded_at"]) <= known_at_epoch:
            if best is None or rev["revision"] > best["revision"]:
                best = rev
    return best


def select_revision(revisions: list[dict], *, as_of_epoch: float | None = None,
                     known_at_epoch: float | None = None) -> dict | None:
    """The general selector behind both `/me` and `/statement`'s temporal
    parameters, combined (R-3-070..078): `known_at` first narrows to the
    revisions that existed from the caller's point of view (R-3-071) —
    if none did, the payment is excluded entirely (R-3-077), never
    zeroed. `as_of` then selects among what's known, by effective time,
    with the same existence-floor `select_revision_as_of` uses (a
    correction can't make a payment predate its own revision 1).
    Omitting a parameter means "no restriction from that axis" (R-3-072):
    omitting both reproduces plain `latest_revision` behaviour
    (R-3-041)."""
    candidates = revisions
    if known_at_epoch is not None:
        candidates = [r for r in candidates if parse_rfc3339(r["recorded_at"]) <= known_at_epoch]
        if not candidates:
            return None

    if as_of_epoch is None:
        return max(candidates, key=lambda r: r["revision"]) if candidates else None

    if not revisions or as_of_epoch < parse_rfc3339(revisions[0]["effective_at"]):
        return None
    best = None
    for rev in candidates:
        if parse_rfc3339(rev["effective_at"]) <= as_of_epoch:
            if best is None or rev["revision"] > best["revision"]:
                best = rev
    return best


def balance_for_view(opening_balances: dict, payments: dict, payment_revisions: dict, user_id: str, *,
                      as_of_epoch: float | None = None, known_at_epoch: float | None = None) -> int:
    """`/me`'s balance under any combination of `as_of`/`known_at`: the
    opening balance plus the net effect of every payment this user is
    party to, each contributing through whichever revision `select_revision`
    picks for it (or nothing, R-3-077)."""
    total = opening_balances.get(user_id, 0)
    for p in payments.values():
        is_from = p["from_user_id"] == user_id
        is_to = p["to_user_id"] == user_id
        if not (is_from or is_to):
            continue
        rev = select_revision(payment_revisions.get(p["id"], []),
                               as_of_epoch=as_of_epoch, known_at_epoch=known_at_epoch)
        if rev is None:
            continue
        total += -rev["amount"] if is_from else rev["amount"]
    return total


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


def latest_revision(revisions: list[dict]) -> dict | None:
    """R-3-038/040/041: the single revision that currently contributes to
    a statement (no `as_of`/`known_at` involved) is the most recently
    recorded one, regardless of its own `effective_at` — with no
    corrections yet (every payment has exactly one revision), this is
    simply that revision, so behaviour is unchanged from before this
    stage's revision machinery existed (R-3-041)."""
    if not revisions:
        return None
    return max(revisions, key=lambda r: r["revision"])


def balance_before(opening_balances: dict, payments: dict, payment_revisions: dict,
                    user_id: str, instant_epoch: float, *, known_at_epoch: float | None = None) -> int:
    """A statement's `opening_balance` (strictly before `from`) and
    `closing_balance` (strictly before `to`, R-3-034) — always through
    each payment's current (latest) revision, never an `as_of`-style
    selection (R-3-038), and strictly `<` rather than `<=` since the
    instant itself is the excluded edge of a half-open window. An
    optional `known_at` narrows "latest" to "latest known as of
    known_at" (R-3-071) — a payment not yet known contributes nothing,
    not a zeroed entry (R-3-077)."""
    total = opening_balances.get(user_id, 0)
    for p in payments.values():
        is_from = p["from_user_id"] == user_id
        is_to = p["to_user_id"] == user_id
        if not (is_from or is_to):
            continue
        revisions = payment_revisions.get(p["id"], [])
        rev = (select_known_revision(revisions, known_at_epoch) if known_at_epoch is not None
               else latest_revision(revisions))
        if rev is None or parse_rfc3339(rev["effective_at"]) >= instant_epoch:
            continue
        total += -rev["amount"] if is_from else rev["amount"]
    return total


def would_candidates_cause_historical_overdraft(opening_balances: dict, payments: dict, payment_revisions: dict,
                                                 candidates: dict, affected_user_ids) -> bool:
    """R-3-060/R-4-050: the general, multi-payment form -- a set of
    proposed revisions (one `(amount, effective_at)` candidate per
    payment id in `candidates`) is illegal if ANY affected user's
    balance would be negative at any effective-time boundary once ALL
    of them are applied TOGETHER, not just the final state. Replays
    each affected user's own payment history in effective-time order,
    using every candidate that applies to that payment and the current
    latest revision for every other payment, batching simultaneous
    movements at the same instant before checking nonnegativity.

    A single correction is the one-candidate case of this; checking
    each of a batch's candidates against everyone else's CURRENT
    (unchanged) revision instead of against the batch's OTHER
    candidates is exactly the gap that lets two individually-boundary-
    safe corrections combine into a real historical negative that
    neither one alone would reveal."""
    for user_id in affected_user_ids:
        events = []
        for p in payments.values():
            is_from = p["from_user_id"] == user_id
            is_to = p["to_user_id"] == user_id
            if not (is_from or is_to):
                continue
            if p["id"] in candidates:
                amount, effective_at = candidates[p["id"]]
            else:
                rev = latest_revision(payment_revisions.get(p["id"], []))
                if rev is None:
                    continue
                amount, effective_at = rev["amount"], rev["effective_at"]
            delta = -amount if is_from else amount
            events.append((parse_rfc3339(effective_at), delta))
        events.sort(key=lambda e: e[0])

        running = opening_balances.get(user_id, 0)
        i, n = 0, len(events)
        while i < n:
            batch_epoch = events[i][0]
            batch_delta = 0
            while i < n and events[i][0] == batch_epoch:
                batch_delta += events[i][1]
                i += 1
            running += batch_delta
            if running < 0:
                return True
    return False


def would_cause_historical_overdraft(opening_balances: dict, payments: dict, payment_revisions: dict,
                                      payment_id: str, candidate_amount: int, candidate_effective_at: str,
                                      affected_user_ids: tuple[str, str]) -> bool:
    """R-3-060: the single-correction case of
    `would_candidates_cause_historical_overdraft` -- one payment's
    proposed revision, checked against everyone else's current latest
    revision."""
    return would_candidates_cause_historical_overdraft(
        opening_balances, payments, payment_revisions,
        {payment_id: (candidate_amount, candidate_effective_at)}, affected_user_ids)


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
