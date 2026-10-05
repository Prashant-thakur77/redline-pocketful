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

from conftest import api_get, api_post, assert_error, auth, idem, n_user_fixture, open_authorization, unique


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

    retried = _batch(tokens[0], [_item(pay["payment_id"], 1, 600)], key=key)
    assert retried.status_code == 201, retried.text


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
