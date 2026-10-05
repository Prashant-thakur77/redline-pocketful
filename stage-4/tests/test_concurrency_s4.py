"""Stage-4 concurrency invariants: R-4-081..083.

R-4-080 (the full-storm invariant, mixing every write path with ~30%
replays) is covered by the extended `invariants/hook.py` (gate 4), not
here -- a standalone pytest file cannot drive the gate's storm harness.
This file covers the three NAMED pairwise races the dispatch calls out
specifically, each with a small, targeted thread pair/group rather than
a full storm.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, n_user_fixture, unique


def _pay(token_from, to_handle, amount=1000):
    r = api_post("/payments", json={"to_handle": to_handle, "amount": amount},
                 headers={**auth(token_from), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()


def test_two_concurrent_refunds_exceeding_cumulative_total_not_both_succeed():
    """R-4-081: two concurrent refunds against the same payment, each
    individually within the current amount but together exceeding it,
    cannot both succeed."""
    fixture, ids, handles, tokens = n_user_fixture(3, balance=10_000)
    pay = _pay(tokens[0], handles[1], amount=1000)

    results = [None, None]

    def refund(i, amount):
        r = api_post(f"/payments/{pay['payment_id']}/refunds", json={"amount": amount},
                    headers={**auth(tokens[1]), **idem(unique(f"refund-race-{i}"))})
        results[i] = r.status_code

    t1 = threading.Thread(target=refund, args=(0, 600))
    t2 = threading.Thread(target=refund, args=(1, 600))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert all(s in (201, 422, 409) for s in results), f"no status outside {{201,422,409}} is legal: {results}"
    assert results.count(201) <= 1, f"two refunds totalling 1200 of a 1000 payment cannot both succeed: {results}"

    balance_a = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    balance_b = api_get("/me", headers=auth(tokens[1])).json()["balance"]
    assert balance_a >= 0 and balance_b >= 0
    assert balance_a + balance_b == 10_000 + 10_000, "money must be conserved regardless of which refund won"


def test_refund_racing_correction_keeps_cumulative_refunds_within_bound_and_balances_nonnegative():
    """R-4-082: a refund and a correction racing the same payment must
    never leave cumulative refunds above the corrected amount, nor either
    party's balance negative."""
    fixture, ids, handles, tokens = n_user_fixture(3, balance=10_000)
    pay = _pay(tokens[0], handles[1], amount=1000)

    results = {}

    def do_refund():
        r = api_post(f"/payments/{pay['payment_id']}/refunds", json={"amount": 900},
                    headers={**auth(tokens[1]), **idem(unique("race-refund"))})
        results["refund"] = r.status_code

    def do_correction():
        r = api_post(f"/payments/{pay['payment_id']}/corrections",
                    json={"expected_revision": 1, "amount": 500,
                          "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                          "reason": "race"},
                    headers={**auth(tokens[0]), **idem(unique("race-correction"))})
        results["correction"] = r.status_code

    t1 = threading.Thread(target=do_refund)
    t2 = threading.Thread(target=do_correction)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert all(s < 500 for s in results.values()), f"no 5xx is legal: {results}"

    balance_a = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    balance_b = api_get("/me", headers=auth(tokens[1])).json()["balance"]
    assert balance_a >= 0 and balance_b >= 0, f"balances went negative under the race: {results}, a={balance_a} b={balance_b}"

    revisions = api_get(f"/payments/{pay['payment_id']}/revisions", headers=auth(tokens[0])).json()
    revs = revisions["revisions"] if isinstance(revisions, dict) else revisions
    current_amount = max(revs, key=lambda rv: rv["revision"])["amount"]

    feed = api_get("/activity", headers=auth(tokens[1])).json()["payments"]
    cumulative_refunded = sum(p["amount"] for p in feed if p.get("refund_of") == pay["payment_id"])
    assert cumulative_refunded <= current_amount, (
        f"cumulative refunds {cumulative_refunded} exceed the current corrected amount "
        f"{current_amount} after the race: {results}")


def test_two_concurrent_batches_sharing_a_payment_not_both_succeed():
    """R-4-083 (R-4-059): two concurrent correction batches, both naming
    the same payment at the same expected_revision, cannot both succeed."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay = _pay(tokens[1], handles[2], amount=1000)

    results = [None, None]

    def batch(i, amount):
        r = api_post("/correction-batches", json={"corrections": [
            {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": amount,
             "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), "reason": f"batch-race-{i}"}
        ]}, headers={**auth(tokens[0]), **idem(unique(f"batch-race-{i}"))})
        results[i] = r.status_code

    t1 = threading.Thread(target=batch, args=(0, 700))
    t2 = threading.Thread(target=batch, args=(1, 800))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert all(s in (201, 409) for s in results), f"no status outside {{201,409}} is legal: {results}"
    assert results.count(201) <= 1, f"two batches sharing a payment at the same revision cannot both succeed: {results}"
