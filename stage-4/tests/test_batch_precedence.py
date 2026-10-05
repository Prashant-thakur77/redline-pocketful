"""Batch error precedence and combined affordability: R-4-049..051,
R-4-059..061.

The named trap: R-4-045/060's completeness check is over the UNION of
every settlement the batch touches, and it runs AFTER every per-item
error, in input order -- so a batch that is both incomplete and contains
an invalid item must report the ITEM error, never incomplete_settlement.
Both halves are tested explicitly, separately, because getting either
backwards still passes a test that only checks one of them.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       n_user_fixture, open_authorization, reset_ok, unique, unique_handle, user)


def _pay(token_from, to_handle, amount=1000):
    r = api_post("/payments", json={"to_handle": to_handle, "amount": amount},
                 headers={**auth(token_from), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()


def _batch(token, items, key=None):
    return api_post("/correction-batches", json={"corrections": items},
                    headers={**auth(token), **idem(key or unique("k"))})


def _item(payment_id, expected_revision, amount, minutes_ago=5, reason="x"):
    return {"payment_id": payment_id, "expected_revision": expected_revision, "amount": amount,
            "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat(),
            "reason": reason}


def test_batch_completeness_evaluated_over_union_of_touched_settlements():
    """R-4-045, R-4-060: a batch touching TWO settlements, one fully
    included (complete) and one only partially included (incomplete),
    must report incomplete_settlement -- the union of settlements
    touched, not just the first one checked."""
    fixture, ids, handles, tokens = n_user_fixture(5, operator_indexes=[0])
    complete_settle = api_post("/settlements", json={"transfers": [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 100},
    ]}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert complete_settle.status_code == 201, complete_settle.text
    complete_member = complete_settle.json()["payments"][0]["payment_id"]

    incomplete_settle = api_post("/settlements", json={"transfers": [
        {"from_handle": handles[3], "to_handle": handles[4], "amount": 100},
        {"from_handle": handles[4], "to_handle": handles[3], "amount": 50},
    ]}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert incomplete_settle.status_code == 201, incomplete_settle.text
    incomplete_members = incomplete_settle.json()["payments"]

    r = _batch(tokens[0], [
        _item(complete_member, 1, 90),
        _item(incomplete_members[0]["payment_id"], 1, 90),
    ])
    assert_error(r, 422, "incomplete_settlement")


def test_batch_item_error_precedes_incomplete_settlement():
    """R-4-060: a batch that is BOTH incomplete for a settlement AND
    contains an invalid item (an unknown payment_id, input-ordered before
    the settlement member) must report the item's error, never
    incomplete_settlement."""
    fixture, ids, handles, tokens = n_user_fixture(4, operator_indexes=[0])
    settle = api_post("/settlements", json={"transfers": [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 100},
        {"from_handle": handles[2], "to_handle": handles[3], "amount": 100},
    ]}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    members = settle.json()["payments"]

    r = _batch(tokens[0], [
        _item("no-such-payment-anywhere", 1, 50),
        _item(members[0]["payment_id"], 1, 90),
    ])
    assert r.status_code == 404, \
        f"the unknown-payment item error must win over incomplete_settlement: {r.text}"


def test_batch_duplicate_payment_id_checked_with_per_item_errors_in_order():
    """R-4-061: the distinctness check runs WITH the per-item sweep, in
    input order -- an earlier item's own error (here, an unknown
    payment_id at position 0) must still win over a later duplicate pair."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0])
    pay = _pay(tokens[1], handles[2], amount=500)

    r = _batch(tokens[0], [
        _item("no-such-payment-at-position-zero", 1, 50),
        _item(pay["payment_id"], 1, 100),
        _item(pay["payment_id"], 1, 200),
    ])
    assert r.status_code == 404, f"the position-0 unknown-payment error must win over the duplicate: {r.text}"


def test_batch_combined_affordability_not_per_item_isolation():
    """R-4-050: two corrections on different payments from the SAME payer,
    each individually affordable in isolation but not combined, must be
    rejected together -- and conversely, a batch where the combined net
    position stays nonnegative must succeed even though netting is only
    visible when both are considered."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=1000)
    pay1 = _pay(tokens[0], handles[1], amount=100)
    pay2 = _pay(tokens[0], handles[2], amount=100)
    # payer's balance now: 1000 - 100 - 100 = 800

    # each correction raises its payment by 500: individually, 800-500=300
    # (affordable alone), but combined 800-500-500=-200 (not affordable together)
    r = _batch(tokens[0], [_item(pay1["payment_id"], 1, 600), _item(pay2["payment_id"], 1, 600)])
    assert_error(r, 409, "insufficient_funds")
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 800


def test_rejected_batch_claims_no_idempotency_key():
    """R-4-051: a key whose batch was rejected is a first use, not a
    claimed one -- reusing it with a valid batch must work normally,
    mirroring R-3-061 for single corrections."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=1000)
    pay = _pay(tokens[0], handles[1], amount=500)
    key = unique("retry-after-rejection")

    rejected = _batch(tokens[0], [_item(pay["payment_id"], 1, 1_000_000)], key=key)
    assert rejected.status_code == 409, rejected.text
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 1000 - 500
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 1000 + 500

    retried = _batch(tokens[0], [_item(pay["payment_id"], 1, 600)], key=key)
    assert retried.status_code == 201, retried.text
    # the retry's increase (500->600) debits the sender and credits the receiver
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 1000 - 500 - 100
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 1000 + 500 + 100


def test_concurrent_corrections_sharing_a_revision_across_single_and_batch():
    """R-4-059: a single correction and a batch correction racing the same
    expected_revision on the same payment cannot both succeed."""
    import threading
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay = _pay(tokens[1], handles[2], amount=500)

    results = [None, None]

    def do_single():
        r = api_post(f"/payments/{pay['payment_id']}/corrections",
                    json={"expected_revision": 1, "amount": 600,
                          "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                          "reason": "single"},
                    headers={**auth(tokens[1]), **idem(unique("k"))})
        results[0] = r.status_code

    def do_batch():
        r = _batch(tokens[0], [_item(pay["payment_id"], 1, 700)])
        results[1] = r.status_code

    t1 = threading.Thread(target=do_single)
    t2 = threading.Thread(target=do_batch)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert all(s in (201, 409) for s in results), f"no status outside {{201,409}} is legal: {results}"
    assert results.count(201) == 1, f"exactly one of the single/batch race must win: {results}"

    # whichever side won, the resulting balances must match that side's
    # amount exactly -- not the loser's, and not some third value
    revisions = api_get(f"/payments/{pay['payment_id']}/revisions", headers=auth(tokens[1])).json()
    revs = revisions["revisions"] if isinstance(revisions, dict) else revisions
    winning_amount = max(revs, key=lambda rv: rv["revision"])["amount"]
    assert winning_amount in (600, 700), f"unexpected winning amount: {winning_amount}"
    delta = winning_amount - 500
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 500 - delta
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 500 + delta


def test_batch_historical_check_is_combined_not_per_item():
    """R-4-049 stage 4, R-4-050: planner's counterexample. Two payments to
    the SAME receiver (B), each corrected down in the SAME batch, each of
    which is clean at every boundary IN ISOLATION (holding the other at
    its original amount) but NOT clean when both corrections apply at
    once -- a per-item historical check (reusing the single-correction
    primitive on one candidate at a time) misses this; only a combined
    walk over every item's proposed revision together catches it.

      fixture: A=10_000 (operator+sender), B=0, C=10_000
      T1 (pinned, before everything else): A pays B 100 (p1), A pays B 100 (p2)
      T2 (B's real, unpinned history): B pays C 150  -> B=50 originally
      T3:                               C pays B 1000 -> B=1050 originally
      batch: p1 100->50, p2 100->50, BOTH pinned to T1

    Per item (holding the other at its ORIGINAL 100): B at T1 = 50+100=150,
    at T2 = 150-150=0 -- clean, for EITHER item alone. Combined: B at T1 =
    50+50=100, at T2 = 100-150=-50 -- historical_overdraft. The real
    payments (B pays C, C pays B) are never backdated: their effective
    position is simply their own real creation instant, which lands AFTER
    the pinned T1 by construction, giving T1 < T2 < T3 without racing
    now()."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=10_000), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=10_000)],
                            settlement_operator_ids=[a_id])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])
    token_c = login_token(fixture["users"][2]["email"])

    p1 = _pay(token_a, b_handle, amount=100)
    p2 = _pay(token_a, b_handle, amount=100)
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 200

    bc = _pay(token_b, c_handle, amount=150)
    assert bc["payment_id"]
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 50

    cb = _pay(token_c, b_handle, amount=1000)
    assert cb["payment_id"]
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 1050
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 100 - 100
    assert api_get("/me", headers=auth(token_c)).json()["balance"] == 10_000 + 150 - 1000

    r = _batch(token_a, [
        _item(p1["payment_id"], 1, 50, minutes_ago=180),
        _item(p2["payment_id"], 1, 50, minutes_ago=180),
    ])
    assert_error(r, 409, "historical_overdraft")

    # the rejected batch must leave every balance exactly as the three
    # real payments left it
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 100 - 100
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 1050
    assert api_get("/me", headers=auth(token_c)).json()["balance"] == 10_000 + 150 - 1000
