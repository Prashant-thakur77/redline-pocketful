"""Payment corrections: R-3-050..069.

ASSUMED CONTRACT (not directly confirmed against a shipped endpoint —
flagged in the N3-T handoff for @planner/@builder to confirm or correct):
  POST /payments/{id}/corrections
    body: {"expected_revision": int, "amount": int, "effective_at": iso8601,
           "reason": str}
    header: Idempotency-Key (required, same replay semantics as every other
    mutating endpoint in this API)
    201 on success, body includes at least "revision" (the new revision
    number) and "amount".
    403 if the caller is not the payment's payer (from_user).
    404 if the payment id does not exist.
    409 stale_revision if expected_revision != the payment's current revision.
    409 insufficient_funds / 409 historical_overdraft if the correction would
    put a balance negative, either at the final state or at some intermediate
    effective instant.
    422 linked_payment_immutable if the payment is settlement- or
    capture-produced (not a direct/request-settling payment eligible for
    correction).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, two_user_fixture, unique, unique_handle, user)


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


def test_correction_by_payer_succeeds_and_updates_balances():
    """R-3-050: a correction from the payer changes both parties' balances
    by the delta between the old and new amount, not by the new amount
    outright."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    r = _correct(token_a, pay_id, expected_revision=1, amount=800)
    assert r.status_code == 201, r.text

    a_balance = api_get("/me", headers=auth(token_a)).json()["balance"]
    b_balance = api_get("/me", headers=auth(token_b)).json()["balance"]
    assert a_balance == 10_000 - 800
    assert b_balance == 800


def test_correction_by_non_payer_is_403():
    """R-3-051: only the payer may correct their own payment."""
    fixture, token_a, token_b = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    r = _correct(token_b, pay_id, expected_revision=1, amount=600)
    assert r.status_code == 403, r.text


def test_correction_unknown_payment_is_404():
    """R-3-052"""
    fixture, token_a, _ = two_user_fixture()
    r = _correct(token_a, "no-such-payment", expected_revision=1, amount=100)
    assert r.status_code == 404, r.text


def test_correction_stale_expected_revision_is_409():
    """R-3-053: the FIRST correction with a stale expected_revision (not
    matching the payment's current revision) must be rejected, leaving the
    payment at its prior revision."""
    fixture, token_a, token_b = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    ok = _correct(token_a, pay_id, expected_revision=1, amount=600)
    assert ok.status_code == 201, ok.text

    stale = _correct(token_a, pay_id, expected_revision=1, amount=700)
    assert_error(stale, 409, "stale_revision")

    # the payment must still be at the amount the successful correction set
    b_balance = api_get("/me", headers=auth(token_b)).json()["balance"]
    assert b_balance == 600


def test_correction_insufficient_funds_rejected():
    """R-3-054: a correction that would push the payer's current balance
    negative must 409, and leave balances untouched."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    r = _correct(token_a, pay_id, expected_revision=1, amount=1000 + 1)
    assert_error(r, 409, "insufficient_funds")

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 500
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500


def test_correction_zero_amount_is_legal_and_distinct_from_rejection():
    """R-3-055: a correction to amount 0 is a legal, distinct case from an
    insufficient-funds rejection — it must succeed and zero out the
    receiver's share of this payment."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    r = _correct(token_a, pay_id, expected_revision=1, amount=0)
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 0


def test_correction_idempotent_retry_same_key_same_body():
    """R-3-056: replaying the exact same correction request (same
    Idempotency-Key, same body) must return the original response verbatim,
    not apply the correction a second time."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)
    key = unique("retry-corr")

    first = _correct(token_a, pay_id, expected_revision=1, amount=700, key=key)
    assert first.status_code == 201, first.text

    replay = _correct(token_a, pay_id, expected_revision=1, amount=700, key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 700


def test_correction_negative_amount_rejected_422():
    """R-3-057: a negative correction amount is a validation error, not a
    business-rule rejection."""
    fixture, token_a, token_b = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    r = _correct(token_a, pay_id, expected_revision=1, amount=-1)
    assert_error(r, 422, "validation_failed")


def test_correction_missing_required_fields_422():
    """R-3-058"""
    fixture, token_a, token_b = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay_id = _make_payment(token_a, b_handle, amount=500)

    for body in (
        {"amount": 100, "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "x"},
        {"expected_revision": 1, "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "x"},
        {"expected_revision": 1, "amount": 100, "reason": "x"},
    ):
        r = api_post(f"/payments/{pay_id}/corrections", json=body,
                     headers={**auth(token_a), **idem(unique("k"))})
        assert_error(r, 422, "validation_failed")


def test_correction_linked_settlement_payment_is_immutable():
    """R-3-069: a payment produced as a settlement member is not a plain
    direct payment the payer can unilaterally correct."""
    a_id, b_id, op_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, op_handle = unique_handle("a"), unique_handle("b"), unique_handle("op")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0), user(op_id, op_handle, balance=0)],
        settlement_operator_ids=[op_id],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_op = login_token(fixture["users"][2]["email"])
    settle = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 10}]},
                      headers={**auth(token_op), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text

    feed = api_get("/activity", headers=auth(token_a)).json()["payments"]
    settlement_payment_id = next(p["payment_id"] for p in feed if p.get("settlement_id"))

    r = _correct(token_a, settlement_payment_id, expected_revision=1, amount=20)
    assert_error(r, 422, "linked_payment_immutable")
