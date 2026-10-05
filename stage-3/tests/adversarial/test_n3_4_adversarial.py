"""Adversarial findings against N3-4 (POST /payments/{id}/corrections,
R-3-050..069). Run against commit 84717fd.
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,  # noqa: E402
                       open_authorization, reset_ok, two_user_fixture, unique, unique_handle, user)


def _make_payment(token_from, to_handle, amount=1000, note="corr-target"):
    r = api_post("/payments", json={"to_handle": to_handle, "amount": amount, "note": note},
                 headers={**auth(token_from), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()["payment_id"]


def _correct(token, payment_id, expected_revision, amount, effective_at=None, reason="correction", key=None):
    body = {"expected_revision": expected_revision, "amount": amount,
            "effective_at": effective_at or datetime.now(timezone.utc).isoformat(), "reason": reason}
    return api_post(f"/payments/{payment_id}/corrections", json=body,
                     headers={**auth(token), **idem(key or unique("k"))})


def test_replay_after_newer_revision_returns_original_revision_200_r_3_057():
    """R-3-057: 'A successful replay returns 200 with that original
    revision, even after newer revisions exist.'"""
    fixture, token_a, _ = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)
    key1 = unique("k1")

    first = _correct(token_a, pay_id, expected_revision=1, amount=700, key=key1)
    assert first.status_code == 201, first.text
    assert first.json()["revision"] == 2

    # A second, genuinely different correction moves the payment to revision 3.
    second = _correct(token_a, pay_id, expected_revision=2, amount=900, key=unique("k2"))
    assert second.status_code == 201, second.text
    assert second.json()["revision"] == 3

    # Replaying the FIRST key, with its original body, must still return
    # that original (revision 2) response, not an error and not revision 3.
    replay = _correct(token_a, pay_id, expected_revision=1, amount=700, key=key1)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json(), (
        f"replay must return the original revision verbatim: got {replay.json()}, expected {first.json()}"
    )


def test_concurrent_corrections_same_expected_revision_exactly_one_wins_r_3_067():
    """R-3-067: concurrent corrections using the same expected_revision
    cannot both succeed: exactly one 201, the other 409 stale_revision."""
    fixture, token_a, _ = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    results = []
    lock = threading.Lock()

    def attempt(amount):
        r = _correct(token_a, pay_id, expected_revision=1, amount=amount, key=unique("race"))
        with lock:
            results.append(r)

    threads = [threading.Thread(target=attempt, args=(600 + i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = sorted(r.status_code for r in results)
    assert statuses.count(201) == 1, f"expected exactly one 201 among concurrent same-revision corrections, got {statuses}"
    assert statuses.count(409) == 7, f"expected the other 7 to be 409 stale_revision, got {statuses}"
    for r in results:
        if r.status_code == 409:
            assert r.json()["error"]["code"] == "stale_revision", r.text


def test_rejected_correction_releases_idempotency_key_for_retry_r_3_061():
    """R-3-061: 'a rejected correction claims no key.' After a 409
    stale_revision rejection, the SAME Idempotency-Key must be usable
    again — as a genuinely new attempt, not stuck replaying the
    rejection and not permanently poisoned."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)
    key = unique("retry-after-reject")

    # Advance the payment to revision 2 first, with a different key.
    bump = _correct(token_a, pay_id, expected_revision=1, amount=600, key=unique("bump"))
    assert bump.status_code == 201, bump.text

    # Now claim `key` with a body that's stale (still targets revision 1).
    stale = _correct(token_a, pay_id, expected_revision=1, amount=700, key=key)
    assert_error(stale, 409, "stale_revision")

    # Retry the SAME key with the CORRECT expected_revision (2): since the
    # key's prior claim was released (never committed), this must be
    # treated as a fresh use and succeed, not bounce off a poisoned key.
    retry = _correct(token_a, pay_id, expected_revision=2, amount=700, key=key)
    assert retry.status_code == 201, (
        f"the idempotency key must be reusable after its claimed operation was rejected, got {retry.status_code}: {retry.text}"
    )
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 700


def test_insufficient_funds_takes_precedence_over_historical_overdraft_r_3_059():
    """R-3-059: 'Current unaffordability takes precedence over historical
    overdraft.' Construct a correction that is both unaffordable right now
    AND would, if it went through, also create a historical overdraft —
    the response must be 409 insufficient_funds, never historical_overdraft."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    # Backdate to before the payment existed (triggers the historical path
    # too) while also asking for far more than A currently has.
    ancient = "2020-01-01T00:00:00+00:00"
    r = _correct(token_a, pay_id, expected_revision=1, amount=5000, effective_at=ancient)
    assert_error(r, 409, "insufficient_funds")


def test_amount_boundaries_r_3_053():
    """R-3-053: amount is an integer 0..1_000_000_000 inclusive."""
    fixture, token_a, _ = two_user_fixture(balance_a=2_000_000_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]

    pay_id = _make_payment(token_a, b_handle, amount=500)
    ok = _correct(token_a, pay_id, expected_revision=1, amount=1_000_000_000)
    assert ok.status_code == 201, ok.text

    pay_id2 = _make_payment(token_a, b_handle, amount=500)
    too_big = _correct(token_a, pay_id2, expected_revision=1, amount=1_000_000_001)
    assert_error(too_big, 422, "validation_failed")

    pay_id3 = _make_payment(token_a, b_handle, amount=500)
    negative = _correct(token_a, pay_id3, expected_revision=1, amount=-1)
    assert_error(negative, 422, "validation_failed")


def test_expected_revision_zero_and_non_integer_rejected_422():
    """R-3-053: expected_revision must be a positive integer."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    zero = _correct(token_a, pay_id, expected_revision=0, amount=600)
    assert_error(zero, 422, "validation_failed")

    pay_id2 = _make_payment(token_a, b_handle, amount=500)
    boolean = api_post(f"/payments/{pay_id2}/corrections",
                        json={"expected_revision": True, "amount": 600,
                              "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "x"},
                        headers={**auth(token_a), **idem(unique("k"))})
    assert_error(boolean, 422, "validation_failed")


def test_reason_length_boundaries_r_3_053():
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]

    pay_id = _make_payment(token_a, b_handle, amount=500)
    exactly_200 = _correct(token_a, pay_id, expected_revision=1, amount=600, reason="x" * 200)
    assert exactly_200.status_code == 201, exactly_200.text

    pay_id2 = _make_payment(token_a, b_handle, amount=500)
    too_long = _correct(token_a, pay_id2, expected_revision=1, amount=600, reason="x" * 201)
    assert_error(too_long, 422, "validation_failed")

    pay_id3 = _make_payment(token_a, b_handle, amount=500)
    empty = _correct(token_a, pay_id3, expected_revision=1, amount=600, reason="")
    assert_error(empty, 422, "validation_failed")


def test_effective_at_strictly_future_is_422_r_3_053():
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    future = "2099-01-01T00:00:00+00:00"
    r = _correct(token_a, pay_id, expected_revision=1, amount=600, effective_at=future)
    assert_error(r, 422, "validation_failed")


def test_effective_at_without_offset_is_422():
    """effective_at follows the RFC 3339-with-explicit-offset rule used
    elsewhere in this stage; a naive (offset-less) timestamp must 422, not
    be silently treated as UTC or 400 malformed_request."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    naive = "2026-01-01T00:00:00"
    r = _correct(token_a, pay_id, expected_revision=1, amount=600, effective_at=naive)
    assert_error(r, 422, "validation_failed")


def test_correction_of_a_capture_is_immutable_422_r_3_066():
    """R-3-066: a correction of a capture-produced payment is 422
    linked_payment_immutable."""
    fixture, token_a, token_b = two_user_fixture(balance_a=2000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    auth_resp = open_authorization(token_a, b_handle, amount=300)
    cap = api_post(f"/authorizations/{auth_resp['authorization_id']}/capture", json={},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text
    capture_payment_id = cap.json().get("payment_id") or cap.json().get("id")
    assert capture_payment_id, f"capture response missing a payment id: {cap.text}"

    r = _correct(token_a, capture_payment_id, expected_revision=1, amount=400)
    assert_error(r, 422, "linked_payment_immutable")


def test_correction_does_not_change_parties_or_visibility_r_3_054():
    """R-3-054: a correction changes neither the parties nor the
    visibility of the payment — the activity feed entry for this payment
    must still name the same two parties after a correction."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    r = _correct(token_a, pay_id, expected_revision=1, amount=777)
    assert r.status_code == 201, r.text

    a_handle = fixture["users"][0]["handle"]
    feed_a = api_get("/activity", headers=auth(token_a)).json()["payments"]
    entry = next(p for p in feed_a if p["payment_id"] == pay_id)
    assert entry["from_handle"] == a_handle, entry
    assert entry["to_handle"] == b_handle, entry
    assert entry["amount"] == 500, "the original payment record must keep its original amount (R-3-062)"
