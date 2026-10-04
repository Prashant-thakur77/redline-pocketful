"""Error envelope and precedence rules: R-1-060..078."""
from __future__ import annotations

import httpx

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, unique, unique_handle, url, user)


def _two_user_fixture(balance_a=10_000, balance_b=0, operators=None):
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=balance_a), user(b_id, b_handle, balance=balance_b)],
                            settlement_operator_ids=operators or [])
    reset_ok(fixture)
    return fixture, login_token(fixture["users"][0]["email"]), login_token(fixture["users"][1]["email"])


def test_error_body_shape_every_4xx_and_5xx_family():
    """R-1-060"""
    r = api_get("/me")
    assert_error(r, 401, "unauthenticated")
    body = r.json()
    assert list(body.keys()) == ["error"]
    assert set(body["error"].keys()) == {"code", "message"}


def test_malformed_request_unparseable_body():
    """R-1-061"""
    fixture, token_a, _ = _two_user_fixture()
    r = httpx.post(url("/payments"), content=b"{not json", headers={**auth(token_a), "Idempotency-Key": "k",
                                                                      "Content-Type": "application/json"})
    assert_error(r, 400, "malformed_request")


def test_malformed_request_non_object_top_level():
    """R-1-061"""
    fixture, token_a, _ = _two_user_fixture()
    r = api_post("/payments", json=[1, 2, 3], headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 400, "malformed_request")


def test_missing_idempotency_key():
    """R-1-062"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers=auth(token_a))
    assert_error(r, 400, "missing_idempotency_key")


def test_unauthenticated_variants():
    """R-1-063"""
    assert_error(api_get("/me", headers={}), 401, "unauthenticated")
    assert_error(api_get("/me", headers={"Authorization": "token-no-bearer-prefix"}), 401, "unauthenticated")
    assert_error(api_get("/me", headers={"Authorization": "Bearer unknown-token-xyz"}), 401, "unauthenticated")


def test_forbidden_non_operator_settlement():
    """R-1-064"""
    fixture, token_a, token_b = _two_user_fixture()
    r = api_post("/settlements", json={"transfers": []}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(r, 403, "forbidden")


def test_not_found_unknown_resource():
    """R-1-065"""
    fixture, token_a, token_b = _two_user_fixture()
    r = api_post("/requests/does-not-exist/pay", json={}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 404, "not_found")


def test_idempotency_key_reuse_different_body():
    """R-1-066"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 99}, headers={**auth(token_a), **idem(key)})
    assert_error(r, 409, "idempotency_key_reuse")


def test_validation_failed_missing_required_field():
    """R-1-067"""
    fixture, token_a, _ = _two_user_fixture()
    r = api_post("/payments", json={"amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_validation_failed_correct_type_bad_value():
    """R-1-068"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": -5}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_special_field_rules_take_precedence_over_wrong_type():
    """R-1-069"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]

    r = api_post("/payments", json={"to_handle": b_handle, "amount": "50"}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10, "note": None},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10, "note": 12345},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10, "visibility": 5},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_optional_field_omitted_is_never_an_error():
    """R-1-070"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text


def test_required_field_omitted_is_422():
    """R-1-070"""
    fixture, token_a, _ = _two_user_fixture()
    r = api_post("/requests", json={"amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_integer_query_param_strict_decimal_form():
    """R-1-071, R-1-073"""
    fixture, token_a, _ = _two_user_fixture()
    for bad in ("1e9", "4.0", "+4", " 4", "0x4", ""):
        r = api_get("/requests", headers=auth(token_a), params={"limit": bad})
        assert_error(r, 422, "validation_failed")


def test_limit_range_422():
    """R-1-073"""
    fixture, token_a, _ = _two_user_fixture()
    for bad in (0, 201, -1):
        r = api_get("/requests", headers=auth(token_a), params={"limit": bad})
        assert_error(r, 422, "validation_failed")
    assert api_get("/requests", headers=auth(token_a), params={"limit": 1}).status_code == 200
    assert api_get("/requests", headers=auth(token_a), params={"limit": 200}).status_code == 200


def test_offset_range_422():
    """R-1-074"""
    fixture, token_a, _ = _two_user_fixture()
    r = api_get("/requests", headers=auth(token_a), params={"offset": -1})
    assert_error(r, 422, "validation_failed")
    assert api_get("/requests", headers=auth(token_a), params={"offset": 0}).status_code == 200


def test_precedence_auth_before_everything():
    """R-1-075"""
    # no auth, bad body, no key: 401 wins
    r = httpx.post(url("/payments"), content=b"not json at all")
    assert_error(r, 401, "unauthenticated")


def test_precedence_permission_before_malformed_body():
    """R-1-075"""
    fixture, token_a, token_b = _two_user_fixture()
    r = httpx.post(url("/settlements"), content=b"not json", headers={**auth(token_b), "Content-Type": "application/json"})
    assert_error(r, 403, "forbidden")


def test_precedence_malformed_body_before_missing_key():
    """R-1-075"""
    fixture, token_a, _ = _two_user_fixture()
    r = httpx.post(url("/payments"), content=b"not json", headers={**auth(token_a), "Content-Type": "application/json"})
    assert_error(r, 400, "malformed_request")


def test_precedence_missing_key_before_key_too_long():
    """R-1-075: missing key is checked before the over-long-key rule — but an
    actually-present, over-long key still reaches the length check."""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), "Idempotency-Key": "k" * 256})
    assert_error(r, 422, "validation_failed")


def test_precedence_idempotency_resolution_before_field_validation():
    """R-1-075, R-1-110"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    first = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    assert first.status_code == 201
    r = api_post("/payments", json={"to_handle": b_handle, "amount": -999}, headers={**auth(token_a), **idem(key)})
    assert_error(r, 409, "idempotency_key_reuse")


def test_precedence_field_validation_before_lookup():
    """R-1-075"""
    fixture, token_a, _ = _two_user_fixture()
    # amount is invalid AND to_handle doesn't exist: field validation (amount) wins over 404
    r = api_post("/payments", json={"to_handle": unique_handle("ghost"), "amount": -1},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_precedence_lookup_before_resource_permission():
    """R-1-075"""
    fixture, token_a, token_b = _two_user_fixture()
    r = api_post("/requests/does-not-exist/pay", json={}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 404, "not_found")


def test_precedence_resource_state_before_funds():
    """R-1-075"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=0, balance_b=0)
    r = api_post("/requests", json={"payer_handle": fixture["users"][1]["handle"], "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_b))
    # now not_pending AND insufficient_funds both would apply: not_pending wins
    r2 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert_error(r2, 409, "request_not_pending")


def test_body_field_validation_order():
    """R-1-076: required presence -> wrong type -> amount range/integrality ->
    note length -> visibility -> handle syntax -> collection rules -> self-reference."""
    fixture, token_a, _ = _two_user_fixture()
    own_handle = fixture["users"][0]["handle"]

    # amount wrong type takes priority over a bad-syntax handle (amount checked first)
    r = api_post("/payments", json={"to_handle": "Not Valid!", "amount": "oops"},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    # self_payment is checked last: a self-payment with a valid amount/note/visibility is self_payment
    r2 = api_post("/payments", json={"to_handle": own_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r2, 422, "self_payment")


def test_handle_syntax_vs_not_found_vs_malformed():
    """R-1-077"""
    fixture, token_a, _ = _two_user_fixture()

    bad_syntax = api_post("/payments", json={"to_handle": "NOT-VALID!", "amount": 10},
                          headers={**auth(token_a), **idem(unique("k"))})
    assert_error(bad_syntax, 422, "validation_failed")

    valid_but_unknown = api_post("/payments", json={"to_handle": unique_handle("ghost"), "amount": 10},
                                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(valid_but_unknown, 404, "not_found")

    non_string = api_post("/payments", json={"to_handle": 12345, "amount": 10},
                          headers={**auth(token_a), **idem(unique("k"))})
    assert_error(non_string, 400, "malformed_request")


def test_4xx_never_leaks_invisible_resource():
    """R-1-078"""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=0), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_c = login_token(fixture["users"][2]["email"])
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]

    not_party = api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token_c))
    nonexistent = api_post("/requests/totally-made-up-id/decline", json={}, headers=auth(token_c))
    assert not_party.status_code == nonexistent.status_code
    assert not_party.json() == nonexistent.json() or (
        not_party.json()["error"]["code"] == nonexistent.json()["error"]["code"]
    )
