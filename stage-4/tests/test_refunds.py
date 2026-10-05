"""Refunds: R-4-001, R-4-010..024.

ASSUMED CONTRACT (the shape is given directly by R-4-010/016/017, so this
is a restatement for the helpers below, not new speculation):
  POST /payments/{payment_id}/refunds
    body: {"amount": int} -- required, Idempotency-Key required.
    201 on success: a payment object (same shape as POST /payments'),
    carrying refund_of == payment_id, request_id: null,
    authorization_id: null, and the ORIGINAL target's note/visibility.
    A replay (same key, same body) is 200 with the original body.
"""
from __future__ import annotations

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       n_user_fixture, open_authorization, reset_ok, two_user_fixture, unique,
                       unique_handle, user)


def _make_payment(token_from, to_handle, amount=1000, note="refund-target", visibility="public"):
    r = api_post("/payments", json={"to_handle": to_handle, "amount": amount, "note": note,
                                     "visibility": visibility},
                 headers={**auth(token_from), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()


def _refund(token, payment_id, amount, key=None):
    return api_post(f"/payments/{payment_id}/refunds", json={"amount": amount},
                    headers={**auth(token), **idem(key or unique("k"))})


def test_refund_requires_idempotency_key():
    """R-4-010: refunds are the ninth idempotent write path."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = api_post(f"/payments/{pay['payment_id']}/refunds", json={"amount": 100}, headers=auth(token_b))
    assert_error(r, 400, "missing_idempotency_key")


def test_refund_by_receiver_succeeds_and_moves_money():
    """R-4-011, R-4-018: the receiver refunds part of what they received;
    money moves from the receiver's available funds back to the sender."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)

    r = _refund(token_b, pay["payment_id"], 200)
    assert r.status_code == 201, r.text

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000 - 500 + 200
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500 - 200


def test_refund_by_non_receiver_is_403():
    """R-4-011: only the original receiver may refund -- the sender
    (a third party to the refund direction) is 403, never 404."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = _refund(token_a, pay["payment_id"], 100)
    assert r.status_code == 403, r.text


def test_refund_unrelated_third_party_is_403():
    """R-4-011: a user with no role in the payment at all is also 403, not 404."""
    fixture, ids, handles, tokens = n_user_fixture(3)
    pay = _make_payment(tokens[0], handles[1], amount=500)
    r = _refund(tokens[2], pay["payment_id"], 100)
    assert r.status_code == 403, r.text


def test_refund_no_token_is_401():
    """R-4-011"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = api_post(f"/payments/{pay['payment_id']}/refunds", json={"amount": 100})
    assert r.status_code == 401, r.text


def test_refund_unknown_payment_is_404():
    """R-4-011"""
    fixture, token_a, _ = two_user_fixture()
    r = _refund(token_a, "no-such-payment-at-all", 100)
    assert r.status_code == 404, r.text


def test_refund_target_may_be_a_request_payment():
    """R-4-012: a request-settled payment can be refunded too."""
    fixture, token_a, token_b = two_user_fixture(balance_a=0, balance_b=1000)
    a_handle = fixture["users"][0]["handle"]
    req = api_post("/requests", json={"payer_handle": fixture["users"][1]["handle"], "amount": 300},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    pay = api_post(f"/requests/{req.json()['request_id']}/pay", json={},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    r = _refund(token_a, pay.json()["payment_id"], 100)
    assert r.status_code == 201, r.text


def test_refund_target_may_be_a_capture():
    """R-4-012: a capture-produced payment can be refunded too."""
    fixture, ids, handles, tokens = n_user_fixture(2)
    hold = open_authorization(tokens[0], handles[1], amount=500)
    cap = api_post(f"/authorizations/{hold['authorization_id']}/capture", json={"amount": 300, "final": True},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text
    payment_id = cap.json().get("payment_id") or cap.json()["payment_ids"][0]

    r = _refund(tokens[0], payment_id, 50)
    assert r.status_code == 201, r.text


def test_refund_of_a_refund_is_422_invalid_refund_target():
    """R-4-013"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    refund = _refund(token_b, pay["payment_id"], 200)
    assert refund.status_code == 201, refund.text

    # the refund payment's receiver is the ORIGINAL sender (a); a tempting
    # second refund flows a->b and targets the refund itself
    second = _refund(token_a, refund.json()["payment_id"], 50)
    assert_error(second, 422, "invalid_refund_target")


def test_refund_invalid_amount_422():
    """R-4-014"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    for amount in (0, -1, 1.5, "100", True, 1_000_000_001):
        r = _refund(token_b, pay["payment_id"], amount)
        assert_error(r, 422, "validation_failed")


def test_refund_exceeds_payment_422():
    """R-4-015"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = _refund(token_b, pay["payment_id"], 501)
    assert_error(r, 422, "refund_exceeds_payment")


def test_refund_cumulative_exceeds_payment_422():
    """R-4-015: two partial refunds that individually fit but cumulatively
    exceed the original amount."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    first = _refund(token_b, pay["payment_id"], 300)
    assert first.status_code == 201, first.text
    second = _refund(token_b, pay["payment_id"], 300)
    assert_error(second, 422, "refund_exceeds_payment")

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000 - 500 + 300
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500 - 300


def test_refund_shape_and_original_note_visibility():
    """R-4-016: refund_of names the target, request_id/authorization_id
    are null, and note/visibility are the ORIGINAL target's, not the
    refund call's own (which carries no note/visibility fields at all)."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500, note="original note", visibility="private")

    r = _refund(token_b, pay["payment_id"], 200)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["refund_of"] == pay["payment_id"]
    assert body["request_id"] is None
    assert body["authorization_id"] is None
    assert body["note"] == "original note"
    assert body["visibility"] == "private"
    assert body["from_user_id"] == pay["to_user_id"]
    assert body["to_user_id"] == pay["from_user_id"]
    assert body["amount"] == 200


def test_refund_replay_returns_original_200():
    """R-4-017"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    key = unique("refund-key")

    first = _refund(token_b, pay["payment_id"], 200, key=key)
    assert first.status_code == 201, first.text
    replay = _refund(token_b, pay["payment_id"], 200, key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    # the replay must not move money a second time
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000 - 500 + 200
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500 - 200


def test_refund_insufficient_available_funds_409():
    """R-4-018: the refund is checked against the receiver's AVAILABLE
    funds; spending the money elsewhere first makes the refund fail."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    a_handle, b_handle = fixture["users"][0]["handle"], fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)

    # b spends most of what they received elsewhere
    spend = api_post("/payments", json={"to_handle": a_handle, "amount": 480},
                     headers={**auth(token_b), **idem(unique("k"))})
    assert spend.status_code == 201, spend.text

    r = _refund(token_b, pay["payment_id"], 100)
    assert_error(r, 409, "insufficient_funds")


def test_refund_never_reopens_request_or_restores_hold():
    """R-4-019: refunding a request-settled payment leaves the request
    `paid`; refunding a capture-produced payment never restores the hold."""
    fixture, token_a, token_b = two_user_fixture(balance_a=0, balance_b=1000)
    a_handle = fixture["users"][0]["handle"]
    req = api_post("/requests", json={"payer_handle": fixture["users"][1]["handle"], "amount": 300},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    req_id = req.json()["request_id"]
    pay = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    r = _refund(token_a, pay.json()["payment_id"], 100)
    assert r.status_code == 201, r.text

    still = api_get("/requests", headers=auth(token_a), params={"limit": 50}).json()["requests"]
    match = next(x for x in still if x["request_id"] == req_id)
    assert match["status"] == "paid", "a refund must never reopen the settled request"


def test_non_refund_payment_exposes_refund_of_null():
    """R-4-020"""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=100)
    assert pay["refund_of"] is None


def test_settlement_member_payment_may_be_refunded_without_changing_membership():
    """R-4-021"""
    a_id, b_id, op_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, op_handle = unique_handle("a"), unique_handle("b"), unique_handle("op")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0), user(op_id, op_handle, balance=0)],
        settlement_operator_ids=[op_id],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])
    token_op = login_token(fixture["users"][2]["email"])

    settle = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 300}]},
                      headers={**auth(token_op), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    settlement_id = settle.json()["settlement_id"]
    settlement_payment_id = settle.json()["payments"][0]["payment_id"]

    r = _refund(token_b, settlement_payment_id, 100)
    assert r.status_code == 201, r.text

    feed = api_get("/activity", headers=auth(token_a)).json()["payments"]
    original = next(p for p in feed if p["payment_id"] == settlement_payment_id)
    assert original["settlement_id"] == settlement_id, "a refund must never change the original's settlement membership"


def test_refund_precedence_404_before_403():
    """R-4-022: an unknown payment is 404 even for a caller who would
    otherwise also fail the receiver check."""
    fixture, token_a, _ = two_user_fixture()
    r = _refund(token_a, "totally-unknown-payment-id", 100)
    assert r.status_code == 404, r.text


def test_refund_precedence_403_before_validation():
    """R-4-022: a non-receiver caller is 403 even when the body is also invalid."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = api_post(f"/payments/{pay['payment_id']}/refunds", json={"amount": -1},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 403, r.text


def test_refund_precedence_invalid_target_before_exceeds_before_funds():
    """R-4-022: target-kind and cumulative-total checks are properties of
    the target, so they precede the funds check -- a refund-of-a-refund
    whose amount ALSO exceeds the (zero further refundable) target and
    whose receiver has insufficient available funds must still report
    invalid_refund_target, not refund_exceeds_payment or insufficient_funds."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    refund = _refund(token_b, pay["payment_id"], 500)
    assert refund.status_code == 201, refund.text

    # a now has 1000 (got the full 500 back); spend it all so funds would
    # also fail, and ask for an absurd amount so refund_exceeds_payment
    # would also apply -- invalid_refund_target must win over both.
    spend = api_post("/payments", json={"to_handle": b_handle, "amount": 1000},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert spend.status_code == 201, spend.text

    second = _refund(token_a, refund.json()["payment_id"], 999999)
    assert_error(second, 422, "invalid_refund_target")


def test_refund_appears_in_activity_and_statement_with_own_revision():
    """R-4-023: a refund is an ordinary payment in /activity and has its
    own revision 1 (R-3-015), nothing exempts it."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500, visibility="public")

    r = _refund(token_b, pay["payment_id"], 200)
    assert r.status_code == 201, r.text
    refund_id = r.json()["payment_id"]

    feed_a = api_get("/activity", headers=auth(token_a)).json()["payments"]
    assert any(p["payment_id"] == refund_id for p in feed_a)

    revisions = api_get(f"/payments/{refund_id}/revisions", headers=auth(token_a))
    assert revisions.status_code == 200, revisions.text
    body = revisions.json()
    revs = body["revisions"] if isinstance(body, dict) else body
    assert len(revs) == 1
    assert revs[0]["revision"] == 1
    assert revs[0]["amount"] == 200
    assert revs[0]["reason"] == ""


def test_refund_of_appears_as_the_immediately_targeted_id():
    """R-4-024: refund_of is the id of the immediately targeted payment,
    never a chain -- since a refund of a refund is rejected (R-4-013), a
    refund's refund_of always points directly at an ordinary payment."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = _make_payment(token_a, b_handle, amount=500)
    r = _refund(token_b, pay["payment_id"], 200)
    assert r.status_code == 201, r.text
    assert r.json()["refund_of"] == pay["payment_id"]
