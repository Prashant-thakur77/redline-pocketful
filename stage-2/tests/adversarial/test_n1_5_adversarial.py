"""Adversarial findings against N1-5 (POST /payments, GET /activity)."""
from __future__ import annotations

import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, login_token, make_fixture,  # noqa: E402
                      reset_ok, signup_ok, unique, unique_handle, user)


def _pay(token, to_handle, amount, key, note=None, visibility=None, extra=None):
    body = {"to_handle": to_handle, "amount": amount}
    if note is not None:
        body["note"] = note
    if visibility is not None:
        body["visibility"] = visibility
    if extra:
        body.update(extra)
    return api_post("/payments", json=body, headers=auth_idem(token, key))


def test_concurrent_identical_payment_exactly_one_201(two_users):
    """R-1-108, over real HTTP this time: 20 concurrent POST /payments with
    the same Idempotency-Key and the same body must produce exactly one
    201 and the rest 200 with an identical body, and the balance must
    move by exactly one payment's amount, not N."""
    a, b = two_users["a"], two_users["b"]
    key = unique("race")

    def attempt(_i):
        return _pay(a["token"], b["handle"], 100, key)

    with ThreadPoolExecutor(20) as pool:
        responses = list(pool.map(attempt, range(20)))

    statuses = Counter(r.status_code for r in responses)
    assert statuses[201] == 1, f"expected exactly one 201, got {dict(statuses)}"
    assert statuses[200] == 19, f"expected 19 replays, got {dict(statuses)}"

    bodies = {r.json().get("payment_id") for r in responses if r.status_code in (200, 201)}
    assert len(bodies) == 1, f"every response must carry the same payment_id, got {bodies}"

    bal_b = api_get("/me", headers=auth(b["token"])).json()["balance"]
    assert bal_b == 100, f"balance must move by exactly one payment, got {bal_b}"


def test_concurrent_overdraft_race_never_goes_negative(two_users):
    """R-1-002: 30 concurrent payments of 1000 each from a payer with
    balance 10000 (room for exactly 10) using 30 *different* idempotency
    keys. Exactly 10 must succeed, the rest 409 insufficient_funds, and
    the payer's final balance must never be negative and must equal
    exactly balance - (successes * amount)."""
    a, b = two_users["a"], two_users["b"]

    def attempt(i):
        return _pay(a["token"], b["handle"], 1000, unique(f"od{i}"))

    with ThreadPoolExecutor(30) as pool:
        responses = list(pool.map(attempt, range(30)))

    statuses = Counter(r.status_code for r in responses)
    assert statuses[201] == 10, f"expected exactly 10 successful payments, got {dict(statuses)}"
    assert statuses[409] == 20, f"expected 20 insufficient_funds, got {dict(statuses)}"

    bal_a = api_get("/me", headers=auth(a["token"])).json()["balance"]
    bal_b = api_get("/me", headers=auth(b["token"])).json()["balance"]
    assert bal_a == 0, f"payer must land at exactly 0, never negative, got {bal_a}"
    assert bal_b == 10_000, f"payee must receive exactly the successful total, got {bal_b}"
    assert bal_a >= 0


def test_concurrent_conflicting_body_same_key_resolves_to_one_winner_and_clean_409s(two_users):
    """R-1-105/106/108 combined: 10 requests with body X and 10 with body Y,
    same Idempotency-Key, fired concurrently. Exactly one request overall
    becomes the first use (201); every request with the *same* body as the
    winner replays (200, identical body); every request with the *other*
    body gets 409 idempotency_key_reuse — never a second 201, never a
    crash, never a request left unanswered."""
    a, b = two_users["a"], two_users["b"]
    key = unique("conflict")

    def attempt(amount):
        return _pay(a["token"], b["handle"], amount, key)

    amounts = [10] * 10 + [20] * 10

    with ThreadPoolExecutor(20) as pool:
        responses = list(pool.map(attempt, amounts))

    statuses = Counter(r.status_code for r in responses)
    assert statuses[201] == 1, f"expected exactly one 201 across both bodies, got {dict(statuses)}"
    assert statuses[409] == 10, f"expected exactly 10 409s (the losing body), got {dict(statuses)}"
    assert statuses[200] == 9, f"expected exactly 9 replays (the winning body minus the winner), got {dict(statuses)}"

    bal_b = api_get("/me", headers=auth(b["token"])).json()["balance"]
    assert bal_b in (10, 20), f"exactly one payment amount must have moved, got balance {bal_b}"


def test_idempotency_bool_vs_number_conflict_over_http(two_users):
    """R-1-106/R-1-110, over real HTTP (migrated from the white-box
    test_n1_4_adversarial.py now that /payments makes this reachable):
    a key claimed with `{"amount": 1, ...}` and replayed with
    `{"amount": true, ...}` must be `409 idempotency_key_reuse`, not a
    `200` replay (Python's bare `==` would say `1 == True`) and not a
    `422` from amount-type validation either — R-1-110 resolves the key
    *before* field validation, so the conflict must win over the
    validation error the second body would otherwise earn on its own.
    """
    a, b = two_users["a"], two_users["b"]
    key = unique("boolconflict")

    r1 = _pay(a["token"], b["handle"], 1, key)
    assert r1.status_code == 201, r1.text

    r2 = api_post("/payments", json={"to_handle": b["handle"], "amount": True},
                  headers=auth_idem(a["token"], key))
    assert_error(r2, 409, "idempotency_key_reuse")


def test_concurrent_failed_claim_is_released_not_cached(two_users):
    """R-1-107 x R-1-108, the subtlest interaction in the layer: when the
    *winner* of a concurrent identical-key race fails (409
    insufficient_funds), the key must be released, not cached as a
    completed response — every waiter must get its own genuine fresh
    attempt, not a replayed failure. If the implementation ever committed
    a failure as "complete", the key would be permanently stuck 409 even
    after the payer's balance recovers.

    20 concurrent identical requests against a payer with balance 0 must
    all fail (no possible success). The real assertion is what happens
    *after*: once the payer's balance recovers, reusing the exact same
    key must succeed with 201 — proof that none of the 20 failures was
    ever cached as the key's permanent outcome.
    """
    a, b = two_users["a"], two_users["b"]
    third_id, third_handle, third_email = unique("u"), unique_handle("funder"), f"{unique('funder')}@example.com"
    reset_ok(make_fixture([
        user(a["id"], a["handle"], balance=0, email=a["email"]),
        user(b["id"], b["handle"], balance=0, email=b["email"]),
        user(third_id, third_handle, balance=500, email=third_email),
    ]))
    a_token = login_token(a["email"])
    third_token = login_token(third_email)
    key = unique("fail-release")

    def attempt(_i):
        return _pay(a_token, b["handle"], 100, key)

    with ThreadPoolExecutor(20) as pool:
        responses = list(pool.map(attempt, range(20)))

    statuses = Counter(r.status_code for r in responses)
    assert statuses[409] == 20, f"payer has balance 0, every attempt must fail, got {dict(statuses)}"

    # Top up the payer so a retry with the same key could actually succeed.
    r_fund = _pay(third_token, a["handle"], 500, unique("topup"))
    assert r_fund.status_code == 201, r_fund.text

    r_retry = _pay(a_token, b["handle"], 100, key)
    assert r_retry.status_code == 201, (
        f"same key after a race of all-failed attempts must still be a fresh first use, got "
        f"{r_retry.status_code}: {r_retry.text}"
    )


def test_concurrent_drain_to_exactly_zero_never_observes_negative_balance(two_users):
    """R-1-002, transiently: 'no balance is ever negative, not even
    transiently'. Drain a payer's balance to exactly zero with 50
    concurrent payments (each a different idempotency key, so all 50 are
    genuine independent operations) while a background poller hammers
    GET /me for that payer throughout. Every single observed balance,
    at every poll, must be within [0, initial_balance] — never negative,
    never above the starting balance."""
    a, b = two_users["a"], two_users["b"]
    initial = 5_000
    reset_ok(make_fixture([
        user(a["id"], a["handle"], balance=initial, email=a["email"]),
        user(b["id"], b["handle"], balance=0, email=b["email"]),
    ]))
    a_token = login_token(a["email"])

    observed = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            r = api_get("/me", headers=auth(a_token))
            if r.status_code == 200:
                observed.append(r.json()["balance"])

    poller = threading.Thread(target=poll)
    poller.start()

    def attempt(i):
        return _pay(a_token, b["handle"], 100, unique(f"drain{i}"))

    with ThreadPoolExecutor(50) as pool:
        responses = list(pool.map(attempt, range(50)))

    stop.set()
    poller.join(timeout=5.0)

    assert all(r.status_code == 201 for r in responses), (
        f"every drain payment should fit exactly: {Counter(r.status_code for r in responses)}"
    )
    assert observed, "the poller must have captured at least one reading"
    assert all(0 <= v <= initial for v in observed), (
        f"observed a balance outside [0, {initial}] during the drain: "
        f"{[v for v in observed if not (0 <= v <= initial)]}"
    )

    final = api_get("/me", headers=auth(a_token)).json()["balance"]
    assert final == 0, f"payer must land at exactly 0 after draining the full balance, got {final}"


def test_self_payment_precedence_over_insufficient_funds(two_users):
    """R-1-075/076: self_payment is a field-validation (step 7) rejection,
    which must fire before the funds check (step 11) even when the
    amount could never be affordable. A self-payment for more than the
    caller's own balance must be 422 self_payment, never 409."""
    a = two_users["a"]
    r = _pay(a["token"], a["handle"], 999_999_999, unique("selfk"))
    assert_error(r, 422, "self_payment")


def test_self_payment_precedence_over_bad_amount(two_users):
    """R-1-076 order: amount validation precedes self-reference. A
    self-payment with an out-of-range amount must report the amount
    error, not self_payment."""
    a = two_users["a"]
    r = _pay(a["token"], a["handle"], 0, unique("selfamt"))
    assert_error(r, 422, "validation_failed")


def test_note_explicit_null_is_422_not_default(two_users):
    """R-1-069/070: an absent note defaults to ''; an explicitly-present
    `null` note is a wrong-type 422, not silently treated as absent."""
    a, b = two_users["a"], two_users["b"]
    r = api_post("/payments", json={"to_handle": b["handle"], "amount": 10, "note": None},
                 headers=auth_idem(a["token"], unique("notenull")))
    assert_error(r, 422, "validation_failed")


def test_visibility_explicit_null_is_422_not_default(two_users):
    """Same absent-vs-null distinction for visibility."""
    a, b = two_users["a"], two_users["b"]
    r = api_post("/payments", json={"to_handle": b["handle"], "amount": 10, "visibility": None},
                 headers=auth_idem(a["token"], unique("visnull")))
    assert_error(r, 422, "validation_failed")


def test_amount_boundary_max_and_over(two_users):
    """R-1-134: amount is 1..1_000_000_000. Exactly the max must be
    accepted (given sufficient balance); one over must be 422."""
    a, b = two_users["a"], two_users["b"]
    richer = make_fixture([
        user(a["id"], a["handle"], balance=1_000_000_000, email=a["email"]),
        user(b["id"], b["handle"], balance=0, email=b["email"]),
    ])
    reset_ok(richer)
    a_token = login_token(a["email"])

    r_max = _pay(a_token, b["handle"], 1_000_000_000, unique("maxamt"))
    assert r_max.status_code == 201, f"max amount must be accepted: {r_max.text}"

    r_over = _pay(a_token, b["handle"], 1_000_000_001, unique("overamt"))
    assert_error(r_over, 422, "validation_failed")


def test_idempotency_key_reused_after_insufficient_funds_is_fresh(two_users):
    """R-1-107: a key reused after the original request failed with a 4xx
    (409 insufficient_funds included) is a genuine first use and may
    succeed."""
    a, b = two_users["a"], two_users["b"]
    key = unique("retry-after-409")

    r1 = _pay(a["token"], b["handle"], 999_999, key)
    assert_error(r1, 409, "insufficient_funds")

    r2 = _pay(a["token"], b["handle"], 500, key)
    assert r2.status_code == 201, f"same key after a 409 must be a fresh first use: {r2.text}"


def test_activity_private_payment_hidden_from_third_party(two_users):
    """R-1-191/R-1-078: a private payment is visible only to its sender
    and receiver; a third, unrelated user sees nothing for it."""
    a, b = two_users["a"], two_users["b"]
    # Can't call reset here without destroying a/b's state; add a third
    # user via signup instead so the existing fixture survives.
    third = signup_ok()

    key = unique("priv")
    r = _pay(a["token"], b["handle"], 42, key, visibility="private")
    assert r.status_code == 201, r.text
    payment_id = r.json()["payment_id"]

    feed = api_get("/activity", headers=auth(third["token"])).json()
    ids = {p["payment_id"] for p in feed["payments"]}
    assert payment_id not in ids, "a private payment leaked into an unrelated third party's activity feed"

    feed_a = api_get("/activity", headers=auth(a["token"])).json()
    assert payment_id in {p["payment_id"] for p in feed_a["payments"]}, "sender must see their own private payment"
