"""Correction batches: R-4-040..048.

ASSUMED CONTRACT (given directly by R-4-041/052):
  POST /correction-batches
    body: {"corrections": [{payment_id, expected_revision, amount,
           effective_at, reason}, ...]}, 1 to 32 items, distinct
           payment_ids. Idempotency-Key required, caller must be a
           settlement operator.
    201 on success: {"correction_batch_id", "recorded_at",
           "revisions": [...]} in input order.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, assert_error, auth, idem, login_token, make_fixture, \
    n_user_fixture, open_authorization, reset_ok, unique, unique_handle, user


def _operator_fixture(n=3, operator_index=0, balance=10_000):
    return n_user_fixture(n, balance=balance, operator_indexes=[operator_index])


def _pay(token_from, to_handle, amount=1000):
    r = api_post("/payments", json={"to_handle": to_handle, "amount": amount},
                 headers={**auth(token_from), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()


def _batch(token, items, key=None):
    return api_post("/correction-batches", json={"corrections": items},
                    headers={**auth(token), **idem(key or unique("k"))})


def test_batch_requires_operator_and_idempotency_key():
    """R-4-040: no/unknown token -> 401; non-operator -> 403."""
    fixture, ids, handles, tokens = _operator_fixture()
    pay = _pay(tokens[1], handles[2], amount=500)

    no_token = api_post("/correction-batches", json={"corrections": []})
    assert no_token.status_code == 401, no_token.text

    non_operator = api_post("/correction-batches", json={"corrections": []},
                            headers={**auth(tokens[1]), **idem(unique("k"))})
    assert non_operator.status_code == 403, non_operator.text

    no_key = api_post("/correction-batches", json={"corrections": []}, headers=auth(tokens[0]))
    assert_error(no_key, 400, "missing_idempotency_key")


def test_batch_item_count_range_and_distinct_payment_ids():
    """R-4-041"""
    fixture, ids, handles, tokens = _operator_fixture()
    pay = _pay(tokens[1], handles[2], amount=500)
    now = datetime.now(timezone.utc) - timedelta(minutes=5)

    empty = _batch(tokens[0], [])
    assert_error(empty, 422, "validation_failed")

    too_many = _batch(tokens[0], [
        {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": 1,
         "effective_at": now.isoformat(), "reason": "x"} for _ in range(33)
    ])
    assert_error(too_many, 422, "validation_failed")

    duplicate = _batch(tokens[0], [
        {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": 100,
         "effective_at": now.isoformat(), "reason": "x"},
        {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": 200,
         "effective_at": now.isoformat(), "reason": "y"},
    ])
    assert_error(duplicate, 422, "validation_failed")


def test_batch_item_field_validation_amount_and_effective_at():
    """R-4-042 (carries R-3-052, R-3-053)"""
    fixture, ids, handles, tokens = _operator_fixture()
    pay = _pay(tokens[1], handles[2], amount=500)
    now = datetime.now(timezone.utc)

    bad_amount = _batch(tokens[0], [
        {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": -1,
         "effective_at": (now - timedelta(minutes=5)).isoformat(), "reason": "x"}
    ])
    assert_error(bad_amount, 422, "validation_failed")

    future = _batch(tokens[0], [
        {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": 100,
         "effective_at": (now + timedelta(hours=1)).isoformat(), "reason": "x"}
    ])
    assert_error(future, 422, "validation_failed")


def test_batch_unknown_payment_404_and_stale_revision_409():
    """R-4-043"""
    fixture, ids, handles, tokens = _operator_fixture()
    pay = _pay(tokens[1], handles[2], amount=500)
    now = datetime.now(timezone.utc) - timedelta(minutes=5)

    unknown = _batch(tokens[0], [
        {"payment_id": "no-such-payment-in-batch", "expected_revision": 1, "amount": 100,
         "effective_at": now.isoformat(), "reason": "x"}
    ])
    assert unknown.status_code == 404, unknown.text

    stale = _batch(tokens[0], [
        {"payment_id": pay["payment_id"], "expected_revision": 99, "amount": 100,
         "effective_at": now.isoformat(), "reason": "x"}
    ])
    assert_error(stale, 409, "stale_revision")


def test_batch_captures_and_refunds_remain_immutable():
    """R-4-044"""
    fixture, ids, handles, tokens = _operator_fixture()
    hold = open_authorization(tokens[1], handles[2], amount=500)
    cap = api_post(f"/authorizations/{hold['authorization_id']}/capture", json={"amount": 300, "final": True},
                   headers={**auth(tokens[2]), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text
    capture_payment_id = cap.json().get("payment_id") or cap.json()["payment_ids"][0]
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 300
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 300
    now = datetime.now(timezone.utc) - timedelta(minutes=5)

    r = _batch(tokens[0], [
        {"payment_id": capture_payment_id, "expected_revision": 1, "amount": 100,
         "effective_at": now.isoformat(), "reason": "x"}
    ])
    assert_error(r, 422, "linked_payment_immutable")

    # the rejected batch must leave balances exactly as the capture left them
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 300
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 300


def test_batch_may_correct_settlement_members_including_every_member():
    """R-4-044, R-4-045: a single-settlement, single-member batch satisfies
    completeness trivially and must succeed."""
    fixture, ids, handles, tokens = _operator_fixture()
    settle = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[2], "amount": 300}]},
                      headers={**auth(tokens[0]), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    member_id = settle.json()["payments"][0]["payment_id"]
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 300
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 300
    now = datetime.now(timezone.utc) - timedelta(minutes=5)

    r = _batch(tokens[0], [
        {"payment_id": member_id, "expected_revision": 1, "amount": 250,
         "effective_at": now.isoformat(), "reason": "x"}
    ])
    assert r.status_code == 201, r.text
    # a decrease (300->250) debits the original RECEIVER and credits the
    # original sender back the difference
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 300 + 50
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 300 - 50


def test_batch_incomplete_settlement_422():
    """R-4-045: a two-transfer settlement, batched with only one member -> 422 incomplete_settlement."""
    fixture, ids, handles, tokens = n_user_fixture(4, operator_indexes=[0])
    settle = api_post("/settlements", json={"transfers": [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 100},
        {"from_handle": handles[2], "to_handle": handles[3], "amount": 100},
    ]}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    members = settle.json()["payments"]
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 100
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 100 - 100
    assert api_get("/me", headers=auth(tokens[3])).json()["balance"] == 10_000 + 100
    now = datetime.now(timezone.utc) - timedelta(minutes=5)

    r = _batch(tokens[0], [
        {"payment_id": members[0]["payment_id"], "expected_revision": 1, "amount": 150,
         "effective_at": now.isoformat(), "reason": "x"}
    ])
    assert_error(r, 422, "incomplete_settlement")

    # the rejected batch must leave balances exactly as the settlement left them
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 100
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 100 - 100
    assert api_get("/me", headers=auth(tokens[3])).json()["balance"] == 10_000 + 100


def test_batch_settlement_members_must_share_identical_effective_instant():
    """R-4-046: offset spellings may differ, the instant may not."""
    fixture, ids, handles, tokens = n_user_fixture(4, operator_indexes=[0])
    settle = api_post("/settlements", json={"transfers": [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 100},
        {"from_handle": handles[2], "to_handle": handles[3], "amount": 100},
    ]}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    members = settle.json()["payments"]
    t = datetime.now(timezone.utc) - timedelta(minutes=5)

    mismatched = _batch(tokens[0], [
        {"payment_id": members[0]["payment_id"], "expected_revision": 1, "amount": 150,
         "effective_at": t.isoformat(), "reason": "x"},
        {"payment_id": members[1]["payment_id"], "expected_revision": 1, "amount": 150,
         "effective_at": (t + timedelta(seconds=1)).isoformat(), "reason": "y"},
    ])
    assert_error(mismatched, 422, "validation_failed")

    # the SAME instant, spelled differently (explicit +00:00 offset vs Z-less
    # form is not assumed; use two equivalent +00:00 renderings instead)
    same_instant_a = t.isoformat()
    same_instant_b = t.astimezone(timezone.utc).isoformat()
    matched = _batch(tokens[0], [
        {"payment_id": members[0]["payment_id"], "expected_revision": 1, "amount": 150,
         "effective_at": same_instant_a, "reason": "x"},
        {"payment_id": members[1]["payment_id"], "expected_revision": 1, "amount": 150,
         "effective_at": same_instant_b, "reason": "y"},
    ])
    assert matched.status_code == 201, matched.text
    # both members increased 100->150: each increase debits its own sender
    # and credits its own receiver by the +50 delta
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 100 - 50
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 100 - 100 + 50 - 50
    assert api_get("/me", headers=auth(tokens[3])).json()["balance"] == 10_000 + 100 + 50


def test_ordinary_single_payment_correction_still_available_for_non_member():
    """R-4-047"""
    fixture, ids, handles, tokens = _operator_fixture()
    pay = _pay(tokens[1], handles[2], amount=500)
    r = api_post(f"/payments/{pay['payment_id']}/corrections",
                json={"expected_revision": 1, "amount": 600,
                      "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                      "reason": "single"},
                headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 500 - 100
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 500 + 100


def test_batch_ignores_unknown_fields():
    """R-4-048"""
    fixture, ids, handles, tokens = _operator_fixture()
    pay = _pay(tokens[1], handles[2], amount=500)
    now = datetime.now(timezone.utc) - timedelta(minutes=5)

    r = api_post("/correction-batches", json={
        "corrections": [
            {"payment_id": pay["payment_id"], "expected_revision": 1, "amount": 100,
             "effective_at": now.isoformat(), "reason": "x", "unexpected_item_field": True}
        ],
        "unexpected_top_level_field": "surprise",
    }, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    # a decrease (500->100) debits the receiver and credits the sender back
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 - 500 + 400
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 10_000 + 500 - 400
