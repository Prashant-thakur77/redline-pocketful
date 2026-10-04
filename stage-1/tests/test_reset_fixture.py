"""Fixture model and `POST /_test/reset`: R-1-030..050."""
from __future__ import annotations

import httpx
import pytest

from conftest import (api_get, api_post, assert_error, auth, idem, login, login_token,
                       make_fixture, reset, reset_ok, unique, unique_handle, url, user)


def test_currency_and_minor_units_declared():
    """R-1-030"""
    a_id = unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=100)], currency="JPY", minor_units=0)
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    r = api_get("/me", headers=auth(token))
    assert r.status_code == 200
    body = r.json()
    assert body["currency"] == "JPY"
    assert body["minor_units"] == 0


@pytest.mark.parametrize("minor_units,currency", [(2, "EUR"), (0, "JPY"), (3, "BHD")])
def test_minor_units_valid_values(minor_units, currency):
    """R-1-030"""
    a_id = unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=10)], currency=currency, minor_units=minor_units)
    r = reset(fixture)
    assert r.status_code == 204


def test_minor_units_out_of_range_rejected():
    """R-1-047"""
    a_id = unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=10)], currency="EUR", minor_units=4)
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_amount_accepts_integral_numeric_forms():
    """R-1-031"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=10_000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    for i, amount in enumerate([1000, 1000.0, 1e3]):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token), **idem(unique(f"k{i}"))})
        assert r.status_code == 201, f"amount {amount!r} rejected: {r.status_code} {r.text}"
        assert r.json()["amount"] == 1000


def test_amount_boolean_or_string_rejected_422():
    """R-1-032"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=10_000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    for amount in (True, "100"):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token), **idem(unique("k"))})
        assert_error(r, 422, "validation_failed")


def test_amount_non_integral_rejected_422():
    """R-1-033"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=10_000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    for amount in (10.5, 1e-1):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token), **idem(unique("k"))})
        assert_error(r, 422, "validation_failed")


def test_handle_uniqueness_and_syntax_enforced_on_reset():
    """R-1-034, R-1-047"""
    a_id, b_id = unique("u"), unique("u")
    same_handle = unique_handle("dup")
    fixture = make_fixture([user(a_id, same_handle, balance=10), user(b_id, same_handle, balance=10)])
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_handle_bad_syntax_rejected_on_reset():
    """R-1-034, R-1-047"""
    a_id = unique("u")
    fixture = make_fixture([user(a_id, "Not-Valid!", balance=10)])
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_handles_identify_users_no_directory_endpoint():
    """R-1-035"""
    r = api_get("/users")
    assert r.status_code in (404, 401), "there must be no user directory/search endpoint"


def test_seeded_user_starts_with_given_balance_and_can_transact():
    """R-1-037, R-1-044"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=0), user(b_id, b_handle, balance=500)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    r = api_get("/me", headers=auth(token_a))
    assert r.status_code == 200
    assert r.json()["balance"] == 0
    # can immediately be paid
    token_b = login_token(fixture["users"][1]["email"])
    pay = api_post("/payments", json={"to_handle": a_handle, "amount": 50},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    # can immediately request money
    req = api_post("/requests", json={"payer_handle": b_handle, "amount": 10},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert req.status_code == 201, req.text


def test_reset_replaces_all_state():
    """R-1-040"""
    a_id = unique("u")
    first = make_fixture([user(a_id, unique_handle("a"), balance=999)])
    reset_ok(first)
    token = login_token(first["users"][0]["email"])
    assert api_get("/me", headers=auth(token)).status_code == 200

    second = make_fixture([user(unique("u"), unique_handle("b"), balance=1)])
    reset_ok(second)
    # the old user's token must no longer resolve to anything servable
    stale = api_get("/me", headers=auth(token))
    assert stale.status_code in (401, 404)
    # and logging in with the old credentials must now fail
    relogin = login(first["users"][0]["email"], first["users"][0]["password"])
    assert relogin.status_code == 401


def test_reset_requires_no_auth_and_is_repeatable():
    """R-1-041"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=1)])
    r1 = api_post("/_test/reset", json=fixture, headers=None)
    assert r1.status_code == 204
    r2 = api_post("/_test/reset", json=fixture)
    assert r2.status_code == 204


def test_seeded_balance_is_post_payment_not_replayed():
    """R-1-043"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    pay_id = unique("p")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=900), user(b_id, b_handle, balance=100)],
        payments=[{"id": pay_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 100,
                   "note": "", "visibility": "public"}],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 900
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 100


def test_negative_balance_rejected_and_prior_state_intact():
    """R-1-045"""
    a_id = unique("u")
    good = make_fixture([user(a_id, unique_handle("a"), balance=42)])
    reset_ok(good)
    token = login_token(good["users"][0]["email"])

    bad = make_fixture([user(unique("u"), unique_handle("b"), balance=-5)])
    r = reset(bad)
    assert_error(r, 422, "validation_failed")

    # prior state (the good fixture) remains fully servable
    still = api_get("/me", headers=auth(token))
    assert still.status_code == 200
    assert still.json()["balance"] == 42


def test_reset_non_json_body_400():
    """R-1-046"""
    r = httpx.post(url("/_test/reset"), content=b"not json {{{", headers={"Content-Type": "application/json"})
    assert_error(r, 400, "malformed_request")


def test_reset_non_object_top_level_400():
    """R-1-046"""
    r = api_post("/_test/reset", json=[1, 2, 3])
    assert_error(r, 400, "malformed_request")


def test_reset_missing_required_user_field_422():
    """R-1-047"""
    fixture = make_fixture([{"id": unique("u"), "email": "a@example.com", "password": "password123",
                              "display_name": "A", "balance": 10}])  # no handle
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_reset_duplicate_user_id_422():
    """R-1-047"""
    dup = unique("u")
    fixture = make_fixture([user(dup, unique_handle("a"), balance=1), user(dup, unique_handle("b"), balance=1)])
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_reset_payment_unknown_user_422():
    """R-1-047"""
    a_id = unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100)],
        payments=[{"id": unique("p"), "from_user_id": a_id, "to_user_id": "no-such-user",
                   "amount": 10, "note": "", "visibility": "public"}],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_reset_request_unknown_user_422():
    """R-1-047"""
    a_id = unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100)],
        requests=[{"id": unique("r"), "requester_id": a_id, "payer_id": "no-such-user",
                   "amount": 10, "note": "", "status": "pending"}],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_reset_bad_seeded_status_422():
    """R-1-047"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100), user(b_id, unique_handle("b"), balance=0)],
        requests=[{"id": unique("r"), "requester_id": a_id, "payer_id": b_id,
                   "amount": 10, "note": "", "status": "not-a-real-status"}],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_reset_accepts_full_fixture_shape():
    """R-1-042"""
    a_id, b_id, op_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, op_handle = unique_handle("a"), unique_handle("b"), unique_handle("op")
    pay_id, req_id = unique("p"), unique("r")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=900), user(b_id, b_handle, balance=100), user(op_id, op_handle, balance=0)],
        payments=[{"id": pay_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 100,
                   "note": "seed", "visibility": "public"}],
        requests=[{"id": req_id, "requester_id": a_id, "payer_id": b_id, "amount": 10,
                   "note": "seed", "status": "pending"}],
        settlement_operator_ids=[op_id],
        currency="BHD", minor_units=3,
    )
    r = reset(fixture)
    assert r.status_code == 204, r.text
    token_op = login_token(fixture["users"][2]["email"])
    settle = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 1}]},
                      headers={**auth(token_op), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text


def test_reset_omits_optional_collections():
    """R-1-048"""
    fixture = {"currency": "EUR", "minor_units": 2, "users": [user(unique("u"), unique_handle("a"), balance=5)]}
    r = reset(fixture)
    assert r.status_code == 204
    token = login_token(fixture["users"][0]["email"])
    reqs = api_get("/requests", headers=auth(token))
    assert reqs.status_code == 200
    assert reqs.json()["requests"] == []
    acts = api_get("/activity", headers=auth(token))
    assert acts.status_code == 200
    assert acts.json()["payments"] == []


def test_reset_ignores_unknown_top_level_fields():
    """R-1-048, R-1-022"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=5)])
    fixture["totally_unknown_field"] = {"nested": True}
    r = reset(fixture)
    assert r.status_code == 204


def test_seeded_pending_request_is_payable_non_pending_is_not():
    """R-1-049"""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    pending_id, declined_id = unique("r"), unique("r")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=100), user(b_id, b_handle, balance=100), user(c_id, c_handle, balance=100)],
        requests=[
            {"id": pending_id, "requester_id": a_id, "payer_id": b_id, "amount": 10, "note": "", "status": "pending"},
            {"id": declined_id, "requester_id": a_id, "payer_id": c_id, "amount": 10, "note": "", "status": "declined"},
        ],
    )
    reset_ok(fixture)
    token_b = login_token(fixture["users"][1]["email"])
    token_c = login_token(fixture["users"][2]["email"])

    pay_pending = api_post(f"/requests/{pending_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert pay_pending.status_code == 201, pay_pending.text

    pay_declined = api_post(f"/requests/{declined_id}/pay", json={}, headers={**auth(token_c), **idem(unique("k"))})
    assert_error(pay_declined, 409, "request_not_pending")


def test_no_admin_balance_endpoint():
    """R-1-050"""
    a_id = unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=10)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    for path in ("/me/balance", "/admin/balance", f"/users/{a_id}/balance"):
        r = api_post(path, json={"balance": 999999}, headers=auth(token))
        assert r.status_code in (404, 405), f"{path} must not exist as a balance-setting endpoint"
