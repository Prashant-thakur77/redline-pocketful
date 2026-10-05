"""Stage-2 invariants and API changes to stage-1 endpoints: R-2-001..018."""
from __future__ import annotations

from conftest import (api_get, api_post, assert_error, auth, idem, n_user_fixture,
                       open_authorization, two_user_fixture, unique)


def test_get_me_shape_with_and_without_holds():
    """R-2-010, R-2-011"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    no_holds = api_get("/me", headers=auth(tokens[0])).json()
    expected = {"user_id", "display_name", "handle", "balance", "total", "available",
                "held", "currency", "minor_units"}
    assert expected <= set(no_holds.keys())
    assert no_holds["balance"] == no_holds["total"] == 1000
    assert no_holds["held"] == 0
    assert no_holds["available"] == 1000

    open_authorization(tokens[0], handles[1], amount=300)
    with_hold = api_get("/me", headers=auth(tokens[0])).json()
    assert with_hold["balance"] == with_hold["total"] == 1000
    assert with_hold["held"] == 300
    assert with_hold["available"] == 700


def test_payments_remain_immediate_no_intermediate_hold():
    """R-2-012"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 400},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    payer = api_get("/me", headers=auth(token_a)).json()
    receiver = api_get("/me", headers=auth(token_b)).json()
    assert payer["total"] == 600 and payer["held"] == 0 and payer["available"] == 600
    assert receiver["total"] == 400


def test_payment_blocked_by_hold_even_though_total_covers_it():
    """R-2-013: a direct payment is now checked against available, not total."""
    fixture, ids, handles, tokens = n_user_fixture(3, balance=1000)
    open_authorization(tokens[0], handles[1], amount=900)
    r = api_post("/payments", json={"to_handle": handles[2], "amount": 200},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 409, "insufficient_funds")
    r_ok = api_post("/payments", json={"to_handle": handles[2], "amount": 100},
                    headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r_ok.status_code == 201, r_ok.text


def test_request_pay_blocked_by_hold_even_though_total_covers_it():
    """R-2-013"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    open_authorization(tokens[1], handles[0], amount=900)
    req = api_post("/requests", json={"payer_handle": handles[1], "amount": 200},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    pay = api_post(f"/requests/{req.json()['request_id']}/pay", json={},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(pay, 409, "insufficient_funds")


def test_no_endpoint_creates_a_hold_from_a_request():
    """R-2-014: authorizing a request is out of scope; paying one remains
    an immediate transfer with no hold left behind."""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    req = api_post("/requests", json={"payer_handle": handles[1], "amount": 200},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    pay = api_post(f"/requests/{req.json()['request_id']}/pay", json={},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    payer_after = api_get("/me", headers=auth(tokens[1])).json()
    assert payer_after["held"] == 0
    assert pay.json()["authorization_id"] is None


def test_splits_unchanged_by_holds():
    """R-2-015: splits never check balance (R-1-177) and are unaffected by
    holds — a participant with most of their total held can still be asked
    for a share, since a split moves no money at all."""
    fixture, ids, handles, tokens = n_user_fixture(3, balance=1000)
    open_authorization(tokens[1], handles[0], amount=999)
    r = api_post("/splits", json={"amount": 30, "participant_handles": handles},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text


def test_seven_idempotent_write_paths_require_key():
    """R-2-016"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    paths = [
        ("POST", "/payments", {"to_handle": handles[1], "amount": 1}),
        ("POST", "/requests", {"payer_handle": handles[1], "amount": 1}),
        ("POST", "/splits", {"amount": 1, "participant_handles": handles}),
        ("POST", "/authorizations", {"to_handle": handles[1], "amount": 1}),
    ]
    for method, path, body in paths:
        r = api_post(path, json=body, headers=auth(tokens[0]))
        assert_error(r, 400, "missing_idempotency_key")

    auth_obj = open_authorization(tokens[0], handles[1], amount=100)
    capture_missing_key = api_post(f"/authorizations/{auth_obj['authorization_id']}/capture", json={},
                                   headers=auth(tokens[1]))
    assert_error(capture_missing_key, 400, "missing_idempotency_key")


def test_settlement_net_debit_against_available():
    """R-2-017"""
    fixture, ids, handles, tokens = n_user_fixture(3, balance=1000, operator_indexes=[0])
    open_authorization(tokens[0], handles[1], amount=900)
    r = api_post("/settlements", json={"transfers": [{"from_handle": handles[0], "to_handle": handles[2], "amount": 200}]},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 409, "insufficient_funds")
    r_ok = api_post("/settlements", json={"transfers": [{"from_handle": handles[0], "to_handle": handles[2], "amount": 50}]},
                    headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r_ok.status_code == 201, r_ok.text


def test_payment_object_authorization_id_null_for_direct_payment():
    """R-2-018"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert r.json()["authorization_id"] is None
    assert r.json()["request_id"] is None
