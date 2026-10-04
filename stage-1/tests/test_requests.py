"""Requests: R-1-150..167."""
from __future__ import annotations

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, unique, unique_handle, user)


def _two_user_fixture(balance_a=10_000, balance_b=0):
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=balance_a), user(b_id, b_handle, balance=balance_b)])
    reset_ok(fixture)
    return fixture, login_token(fixture["users"][0]["email"]), login_token(fixture["users"][1]["email"])


def test_create_request_shape():
    """R-1-150"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 50, "note": "rent"},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    expected = {"request_id", "requester_id", "requester_handle", "payer_id", "payer_handle",
                "amount", "currency", "note", "status", "payment_id", "created_at"}
    assert expected <= set(body.keys())
    assert body["status"] == "pending"
    assert body["payment_id"] is None
    assert body["requester_handle"] == fixture["users"][0]["handle"]
    assert body["payer_handle"] == b_handle


def test_request_ignores_payer_balance():
    """R-1-151"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=0, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 1_000_000},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    req_id = r.json()["request_id"]

    # the request is created despite the payer's zero balance, and sits pending
    pay_attempt = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(pay_attempt, 409, "insufficient_funds")
    still = api_get("/requests", headers=auth(token_a))
    matching = [x for x in still.json()["requests"] if x["request_id"] == req_id]
    assert matching and matching[0]["status"] == "pending"


def test_request_becomes_payable_once_funds_arrive():
    """R-1-151"""
    a_id, b_id, funder_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, funder_handle = unique_handle("a"), unique_handle("b"), unique_handle("f")
    fixture = make_fixture([user(a_id, a_handle, balance=0), user(b_id, b_handle, balance=0),
                             user(funder_id, funder_handle, balance=1000)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])
    token_funder = login_token(fixture["users"][2]["email"])

    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 500},
                 headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]

    too_poor = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(too_poor, 409, "insufficient_funds")

    fund = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                    headers={**auth(token_funder), **idem(unique("k"))})
    assert fund.status_code == 201, fund.text

    now_payable = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert now_payable.status_code == 201, now_payable.text


def test_request_no_visibility_and_not_in_activity():
    """R-1-152"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert "visibility" not in r.json()
    assert api_get("/activity", headers=auth(token_a)).json()["payments"] == []


def test_request_field_errors():
    """R-1-153"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    own_handle = fixture["users"][0]["handle"]

    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 0}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/requests", json={"payer_handle": own_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "self_request")

    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10, "note": "x" * 201},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/requests", json={"payer_handle": unique_handle("ghost"), "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 404, "not_found")


def test_request_lifecycle_terminal_states():
    """R-1-154"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    pay = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    status = api_get("/requests", headers=auth(token_a)).json()["requests"]
    matching = [x for x in status if x["request_id"] == req_id][0]
    assert matching["status"] == "paid"
    cancel_attempt = api_post(f"/requests/{req_id}/cancel", json={}, headers=auth(token_a))
    assert_error(cancel_attempt, 409, "request_not_pending")


def test_pay_request_payer_only_shape():
    """R-1-155"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    pay = api_post(f"/requests/{req_id}/pay", json={"visibility": "private"},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    body = pay.json()
    expected = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                "amount", "currency", "note", "visibility", "request_id", "created_at", "settlement_id"}
    assert expected <= set(body.keys())
    assert body["request_id"] == req_id
    assert body["visibility"] == "private"


def test_pay_request_visibility_is_payers_choice():
    """R-1-156"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    pay = api_post(f"/requests/{req_id}/pay", json={"visibility": "private"},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    requests_list = api_get("/requests", headers=auth(token_a)).json()["requests"]
    matching = [x for x in requests_list if x["request_id"] == req_id][0]
    assert matching["status"] == "paid"
    assert matching["payment_id"] == pay.json()["payment_id"]


def test_pay_body_distinguishes_empty_from_explicit_default():
    """R-1-157"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    key = unique("pay-key")
    r1 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post(f"/requests/{req_id}/pay", json={"visibility": "public"}, headers={**auth(token_b), **idem(key)})
    assert_error(r2, 409, "idempotency_key_reuse")


def test_pay_not_pending_insufficient_funds_forbidden_not_found():
    """R-1-158"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=0, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]

    # not the payer
    forbidden = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(forbidden, 403, "forbidden")

    # insufficient funds (payer balance 0)
    poor = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(poor, 409, "insufficient_funds")

    # unknown request id
    unknown = api_post("/requests/does-not-exist/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(unknown, 404, "not_found")

    # now decline then try to pay: not pending
    decline = api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_b))
    assert decline.status_code == 200, decline.text
    not_pending = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(not_pending, 409, "request_not_pending")


def test_replaying_successful_pay_never_409s():
    """R-1-159"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    key = unique("pay-key")
    r1 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(key)})
    assert r1.status_code == 201, r1.text
    before = api_get("/me", headers=auth(token_b)).json()["balance"]
    r2 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(key)})
    assert r2.status_code == 200, r2.text
    assert r1.json() == r2.json()
    after = api_get("/me", headers=auth(token_b)).json()["balance"]
    assert before == after


def test_decline_request():
    """R-1-160"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]

    forbidden = api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_a))
    assert_error(forbidden, 403, "forbidden")

    r1 = api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_b))
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "declined"

    r2 = api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_b))
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "declined"

    unknown = api_post("/requests/nope/decline", json={}, headers=auth(token_b))
    assert_error(unknown, 404, "not_found")

    r3 = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id3 = r3.json()["request_id"]
    pay = api_post(f"/requests/{req_id3}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    stale_decline = api_post(f"/requests/{req_id3}/decline", json={}, headers=auth(token_b))
    assert_error(stale_decline, 409, "request_not_pending")


def test_cancel_request():
    """R-1-161"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]

    forbidden = api_post(f"/requests/{req_id}/cancel", json={}, headers=auth(token_b))
    assert_error(forbidden, 403, "forbidden")

    r1 = api_post(f"/requests/{req_id}/cancel", json={}, headers=auth(token_a))
    assert r1.status_code == 200, r1.text
    assert r1.json()["status"] == "cancelled"

    r2 = api_post(f"/requests/{req_id}/cancel", json={}, headers=auth(token_a))
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "cancelled"

    unknown = api_post("/requests/nope/cancel", json={}, headers=auth(token_a))
    assert_error(unknown, 404, "not_found")

    r3 = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id3 = r3.json()["request_id"]
    decline = api_post(f"/requests/{req_id3}/decline", json={}, headers=auth(token_b))
    assert decline.status_code == 200
    stale_cancel = api_post(f"/requests/{req_id3}/cancel", json={}, headers=auth(token_a))
    assert_error(stale_cancel, 409, "request_not_pending")


def test_decline_and_cancel_move_no_money():
    """R-1-162"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=1000, balance_b=1000)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_b))
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 1000

    r2 = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id2 = r2.json()["request_id"]
    api_post(f"/requests/{req_id2}/cancel", json={}, headers=auth(token_a))
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 1000


def test_get_requests_visible_only_to_participants():
    """R-1-163"""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=0), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_c = login_token(fixture["users"][2]["email"])
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    c_view = api_get("/requests", headers=auth(token_c)).json()["requests"]
    assert all(x["request_id"] != req_id for x in c_view)
    a_view = api_get("/requests", headers=auth(token_a)).json()["requests"]
    assert any(x["request_id"] == req_id for x in a_view)


def test_get_requests_newest_first():
    """R-1-163"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    for i in range(3):
        api_post("/requests", json={"payer_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(unique(f"k{i}"))})
    items = api_get("/requests", headers=auth(token_a)).json()["requests"]
    created = [x["created_at"] for x in items]
    assert created == sorted(created, reverse=True)


def test_get_requests_direction_filter():
    """R-1-164"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    a_handle = fixture["users"][0]["handle"]
    out_r = api_post("/requests", json={"payer_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(unique("k"))})
    out_id = out_r.json()["request_id"]
    in_r = api_post("/requests", json={"payer_handle": a_handle, "amount": 1}, headers={**auth(token_b), **idem(unique("k"))})
    in_id = in_r.json()["request_id"]

    outgoing = api_get("/requests", headers=auth(token_a), params={"direction": "outgoing"}).json()["requests"]
    assert any(x["request_id"] == out_id for x in outgoing)
    assert all(x["request_id"] != in_id for x in outgoing)

    incoming = api_get("/requests", headers=auth(token_a), params={"direction": "incoming"}).json()["requests"]
    assert any(x["request_id"] == in_id for x in incoming)
    assert all(x["request_id"] != out_id for x in incoming)


def test_get_requests_status_filter_and_unknown_value_422():
    """R-1-165"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_b))

    declined = api_get("/requests", headers=auth(token_a), params={"status": "declined"}).json()["requests"]
    assert all(x["status"] == "declined" for x in declined)

    bad = api_get("/requests", headers=auth(token_a), params={"status": "bogus"})
    assert_error(bad, 422, "validation_failed")

    bad_dir = api_get("/requests", headers=auth(token_a), params={"direction": "sideways"})
    assert_error(bad_dir, 422, "validation_failed")


def test_get_requests_pagination_defaults_and_has_more():
    """R-1-166, R-1-167"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    for i in range(5):
        api_post("/requests", json={"payer_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(unique(f"k{i}"))})

    default_page = api_get("/requests", headers=auth(token_a))
    assert default_page.status_code == 200
    assert default_page.json()["has_more"] is False  # fewer than 50 total

    page = api_get("/requests", headers=auth(token_a), params={"limit": 2, "offset": 0})
    body = page.json()
    assert len(body["requests"]) == 2
    assert body["has_more"] is True

    past_end = api_get("/requests", headers=auth(token_a), params={"limit": 2, "offset": 1000})
    assert past_end.json()["requests"] == []
    assert past_end.json()["has_more"] is False
