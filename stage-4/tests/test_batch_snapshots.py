"""Batch commit semantics, and the snapshot-leak trap: R-4-052..058.

Two named traps:
- R-4-053: a batch's one shared `recorded_at` must be strictly later than
  the previous `recorded_at` of EVERY member. A naive now() can tie with a
  correction recorded in the same tick, so this is tested with a single
  correction immediately followed by a batch touching that same payment,
  asserting strict `>`, never `>=`.
- R-4-057: a batch is the largest single mutation in the product, so it is
  the most likely thing to leak into a snapshot token R-3-005 already
  froze. A token is taken BEFORE a batch that moves a payment's revision,
  and the token must still page byte-identical entries and balances after.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, n_user_fixture, unique


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


def _revisions(token, payment_id):
    r = api_get(f"/payments/{payment_id}/revisions", headers=auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    return body["revisions"] if isinstance(body, dict) else body


def test_batch_success_shape_and_input_order():
    """R-4-052"""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay1 = _pay(tokens[1], handles[2], amount=100)
    pay2 = _pay(tokens[2], handles[1], amount=200)

    r = _batch(tokens[0], [_item(pay1["payment_id"], 1, 150), _item(pay2["payment_id"], 1, 250)])
    assert r.status_code == 201, r.text
    body = r.json()
    assert "correction_batch_id" in body and "recorded_at" in body
    assert [rv["payment_id"] for rv in body["revisions"]] == [pay1["payment_id"], pay2["payment_id"]]


def test_batch_revisions_expose_batch_id_singles_expose_null():
    """R-4-054"""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay1 = _pay(tokens[1], handles[2], amount=100)
    pay2 = _pay(tokens[2], handles[1], amount=200)

    single = api_post(f"/payments/{pay1['payment_id']}/corrections",
                      json={"expected_revision": 1, "amount": 150,
                            "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                            "reason": "single"},
                      headers={**auth(tokens[1]), **idem(unique("k"))})
    assert single.status_code == 201, single.text
    single_revisions = _revisions(tokens[1], pay1["payment_id"])
    assert single_revisions[-1].get("correction_batch_id") is None

    batch = _batch(tokens[0], [_item(pay2["payment_id"], 1, 250)])
    assert batch.status_code == 201, batch.text
    batch_id = batch.json()["correction_batch_id"]
    batch_revisions = _revisions(tokens[2], pay2["payment_id"])
    assert batch_revisions[-1].get("correction_batch_id") == batch_id


def test_batch_shared_recorded_at_strictly_later_than_every_prior_one():
    """R-4-053: a single correction on payment P, then immediately a batch
    touching P again -- the batch's shared recorded_at must be strictly
    LATER than P's own previous recorded_at, never equal, even when both
    happen in the same wall-clock tick."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay = _pay(tokens[1], handles[2], amount=100)

    single = api_post(f"/payments/{pay['payment_id']}/corrections",
                      json={"expected_revision": 1, "amount": 150,
                            "effective_at": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
                            "reason": "single"},
                      headers={**auth(tokens[1]), **idem(unique("k"))})
    assert single.status_code == 201, single.text
    revision_2_recorded_at = _revisions(tokens[1], pay["payment_id"])[-1]["recorded_at"]

    batch = _batch(tokens[0], [_item(pay["payment_id"], 2, 175)])
    assert batch.status_code == 201, batch.text
    revisions_after_batch = _revisions(tokens[1], pay["payment_id"])
    revision_3 = revisions_after_batch[-1]
    assert revision_3["revision"] == 3
    assert revision_3["recorded_at"] > revision_2_recorded_at, \
        f"batch recorded_at {revision_3['recorded_at']} must be strictly later than the prior " \
        f"revision's {revision_2_recorded_at}, never equal"


def test_batch_shared_recorded_at_identical_across_every_member():
    """R-4-053: every new revision IN one batch shares the SAME recorded_at."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay1 = _pay(tokens[1], handles[2], amount=100)
    pay2 = _pay(tokens[2], handles[1], amount=200)

    r = _batch(tokens[0], [_item(pay1["payment_id"], 1, 150), _item(pay2["payment_id"], 1, 250)])
    assert r.status_code == 201, r.text
    rev1 = _revisions(tokens[1], pay1["payment_id"])[-1]
    rev2 = _revisions(tokens[2], pay2["payment_id"])[-1]
    assert rev1["recorded_at"] == rev2["recorded_at"] == r.json()["recorded_at"]


def test_batch_never_changes_original_payment_or_its_retry_identity():
    """R-4-056: a batch correcting a payment must not change the ORIGINAL
    creation call's own idempotent retry identity."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay_key = unique("original-pay-key")
    pay = api_post("/payments", json={"to_handle": handles[2], "amount": 100},
                   headers={**auth(tokens[1]), **idem(pay_key)})
    assert pay.status_code == 201, pay.text

    batch = _batch(tokens[0], [_item(pay.json()["payment_id"], 1, 150)])
    assert batch.status_code == 201, batch.text

    replay = api_post("/payments", json={"to_handle": handles[2], "amount": 100},
                      headers={**auth(tokens[1]), **idem(pay_key)})
    assert replay.status_code == 200, replay.text
    assert replay.json() == pay.json(), \
        "the original payment's own retry identity must be unaffected by a later batch correction"


def test_batch_replay_returns_original_response():
    """R-4-058"""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay = _pay(tokens[1], handles[2], amount=100)
    key = unique("batch-key")
    item = _item(pay["payment_id"], 1, 150)

    first = _batch(tokens[0], [item], key=key)
    assert first.status_code == 201, first.text
    replay = _batch(tokens[0], [item], key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()


def test_snapshot_token_survives_a_batch_moving_its_window():
    """R-4-057: take a statement snapshot BEFORE a batch that corrects a
    payment inside that snapshot's window, then assert the token still
    pages byte-identical entries and balances -- the batch must not leak
    into a frozen result."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay = _pay(tokens[1], handles[2], amount=100)

    before = api_get("/statement", headers=auth(tokens[1]), params={"limit": 5})
    assert before.status_code == 200, before.text
    token_value = before.json().get("snapshot")
    assert token_value, "a statement page must carry a snapshot token to test R-4-057 against"

    batch = _batch(tokens[0], [_item(pay["payment_id"], 1, 999)])
    assert batch.status_code == 201, batch.text

    after = api_get("/statement", headers=auth(tokens[1]), params={"limit": 5, "snapshot": token_value})
    assert after.status_code == 200, after.text
    assert after.json() == before.json(), \
        f"the pre-batch snapshot page changed after the batch: before={before.json()} after={after.json()}"
