"""Corrections after refunds, and refunds after corrections: R-4-030..034.

The stage's most expensive trap, named directly in the dispatch: R-4-015
(refund ceiling = CURRENT corrected amount) and R-4-033 (correction floor =
already-refunded amount) are two directions of one constraint. A service
storing only the original amount gets both wrong, and testing each in
isolation at revision 1 never notices -- so every test here interleaves a
refund and a correction on the SAME payment and asserts the resulting
balances, not only the status codes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, assert_error, auth, idem, n_user_fixture, open_authorization, two_user_fixture, unique


def _make_payment(token_from, to_handle, amount=1000):
    r = api_post("/payments", json={"to_handle": to_handle, "amount": amount},
                 headers={**auth(token_from), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()


def _correct(token, payment_id, expected_revision, amount, effective_at=None):
    return api_post(f"/payments/{payment_id}/corrections",
                    json={"expected_revision": expected_revision, "amount": amount,
                          "effective_at": (effective_at or datetime.now(timezone.utc)).isoformat(),
                          "reason": "interleave"},
                    headers={**auth(token), **idem(unique("k"))})


def _refund(token, payment_id, amount):
    return api_post(f"/payments/{payment_id}/refunds", json={"amount": amount},
                    headers={**auth(token), **idem(unique("k"))})


def test_corrections_remain_available_for_direct_and_request_payments():
    """R-4-030"""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = _correct(token_a, pay["payment_id"], 1, 600)
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 600
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 600


def test_capture_cannot_be_corrected():
    """R-4-031 (carries R-3-066)"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    hold = open_authorization(tokens[0], handles[1], amount=500)
    cap = api_post(f"/authorizations/{hold['authorization_id']}/capture", json={"amount": 300, "final": True},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text
    payment_id = cap.json().get("payment_id") or cap.json()["payment_ids"][0]
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 10_000 - 300
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 + 300

    r = _correct(tokens[0], payment_id, 1, 200)
    assert_error(r, 422, "linked_payment_immutable")

    # the rejected correction attempt must leave balances exactly as the capture left them
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 10_000 - 300
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 10_000 + 300


def test_refund_cannot_itself_be_corrected():
    """R-4-032: a refund payment is immutable."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    refund = _refund(token_b, pay["payment_id"], 200)
    assert refund.status_code == 201, refund.text
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000 - 500 + 200
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500 - 200

    # corrections require the payment's SENDER (R-3-051), not its receiver --
    # the refund flows b->a, so b is the sender and is the one who would
    # attempt to correct it
    r = _correct(token_b, refund.json()["payment_id"], 1, 50)
    assert_error(r, 422, "linked_payment_immutable")

    # the rejected correction attempt must leave balances exactly as the refund left them
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000 - 500 + 200
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500 - 200


def test_correction_may_not_reduce_below_already_refunded_amount():
    """R-4-033: refund 300 of 1000, then correct down to 250 -- the floor
    is the already-refunded amount (300), so 250 must be rejected."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=1000)

    refund = _refund(token_b, pay["payment_id"], 300)
    assert refund.status_code == 201, refund.text

    r = _correct(token_a, pay["payment_id"], 1, 250)
    assert_error(r, 422, "refund_exceeds_payment")

    # balances must be exactly as the refund alone left them
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 1000 + 300
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 1000 - 300


def test_correction_down_to_exactly_the_refunded_amount_succeeds():
    """R-4-033 boundary: correcting down to EXACTLY the already-refunded
    amount is the accept side -- the floor is inclusive.

    R-4-036: a correction's effective_at reorders its payment relative to
    movements that already happened against the pre-correction amount. A
    now()-dated correction here would land AFTER the refund in replay
    order, so the corrected (lower) amount would not yet be in effect when
    the refund debits b, landing b at a negative boundary (409
    historical_overdraft) even though the final state is fine. Pinning
    effective_at to before the refund (here, the original payment's
    instant) keeps the corrected amount in effect when the refund replays,
    which is the scenario this test is actually about."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    before_refund = datetime.now(timezone.utc) - timedelta(minutes=1)
    pay = _make_payment(token_a, b_handle, amount=1000)

    refund = _refund(token_b, pay["payment_id"], 300)
    assert refund.status_code == 201, refund.text

    r = _correct(token_a, pay["payment_id"], 1, 300, effective_at=before_refund)
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 0


def test_correction_raises_ceiling_then_a_larger_refund_succeeds():
    """R-4-015: correct 1000 up to 2000, then refund 1500 -- the ceiling is
    the CURRENT corrected amount (2000), not the original (1000), so a
    refund larger than the original must succeed."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=1000)

    corr = _correct(token_a, pay["payment_id"], 1, 2000)
    assert corr.status_code == 201, corr.text
    # a's balance after correction: 10000 - 2000 = 8000; b's: 2000
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 8000
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 2000

    refund = _refund(token_b, pay["payment_id"], 1500)
    assert refund.status_code == 201, \
        f"a refund larger than the ORIGINAL (1000) but within the corrected amount (2000) must succeed: {refund.text}"
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 8000 + 1500
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 2000 - 1500


def test_correction_lowers_ceiling_then_refund_exceeding_it_rejected():
    """R-4-015: a service that stores only the original amount would let
    this refund through at 1000 since that was the original -- but the
    ceiling after the correction is 400, so a 500 refund must be rejected."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=1000)

    corr = _correct(token_a, pay["payment_id"], 1, 400)
    assert corr.status_code == 201, corr.text

    refund = _refund(token_b, pay["payment_id"], 500)
    assert_error(refund, 422, "refund_exceeds_payment")

    # the rejected refund must leave balances exactly as the correction left them
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 400
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 400


def test_correction_debits_checked_against_available_not_total():
    """R-4-034: amends R-3-058 -- a correction that increases a payer's
    debit is checked against AVAILABLE funds (balance minus held), not
    total, so an open hold on the payer's wallet can make an otherwise-
    affordable correction fail."""
    fixture, ids, handles, tokens = n_user_fixture(2)
    pay = _make_payment(tokens[0], handles[1], amount=100)

    # tie up most of the payer's remaining balance in an open hold
    hold = open_authorization(tokens[0], handles[1], amount=9800)
    me = api_get("/me", headers=auth(tokens[0])).json()
    assert me["available"] == 10_000 - 100 - 9800  # 100

    # raising the payment's amount by 200 is affordable against TOTAL
    # (9900 total - 300 = 9600 >= 0) but not against AVAILABLE (100 - 200 < 0)
    r = _correct(tokens[0], pay["payment_id"], 1, 300)
    assert_error(r, 409, "insufficient_funds")


def test_correction_decrease_debits_receiver_who_cannot_currently_afford_it():
    """R-4-037(b): a DECREASE takes money back from the original RECEIVER
    (s3: "decreasing it debits the original receiver"), so it must be
    funds-checked against the receiver's current available, exactly like
    an increase is checked against the sender's. Planner's counterexample:
    a pays b 1000 (b=1000); b pays it mostly away (b=100); a corrects the
    payment down to 0, which needs to debit b the full 1000 -- b can only
    afford 100 of it, so this must be insufficient_funds, not
    historical_overdraft and not a silent success."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    a_handle = fixture["users"][0]["handle"]
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=1000)

    spend = _make_payment(token_b, a_handle, amount=900)
    assert spend["payment_id"]
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 100

    r = _correct(token_a, pay["payment_id"], 1, 0)
    assert_error(r, 409, "insufficient_funds")

    # the rejected correction must leave balances exactly as the spend left them
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_000 - 1000 + 900
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 100
