"""Splits: R-1-170..180."""
from __future__ import annotations

import pytest

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, unique, unique_handle, user)


def _n_user_fixture(n, balance=0):
    ids = [unique("u") for _ in range(n)]
    handles = [unique_handle(f"p{i}") for i in range(n)]
    fixture = make_fixture([user(ids[i], handles[i], balance=balance) for i in range(n)])
    reset_ok(fixture)
    tokens = [login_token(fixture["users"][i]["email"]) for i in range(n)]
    return fixture, handles, tokens


def test_split_creates_requests_for_everyone_but_caller():
    """R-1-170"""
    fixture, handles, tokens = _n_user_fixture(3)
    r = api_post("/splits", json={"amount": 300, "participant_handles": handles, "note": "dinner"},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    payer_handles = {req["payer_handle"] for req in body["requests"]}
    assert handles[0] not in payer_handles
    assert payer_handles == {handles[1], handles[2]}
    for req in body["requests"]:
        assert req["requester_handle"] == handles[0]
        assert req["status"] == "pending"


def test_split_response_shape():
    """R-1-171"""
    fixture, handles, tokens = _n_user_fixture(3)
    r = api_post("/splits", json={"amount": 300, "participant_handles": handles, "note": "dinner"},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    expected = {"split_id", "amount", "currency", "note", "shares", "requests", "created_at"}
    assert expected <= set(body.keys())
    share_handles = [s["handle"] for s in body["shares"]]
    assert share_handles == handles  # every participant including the caller, in order
    request_handles = [req["payer_handle"] for req in body["requests"]]
    assert request_handles == handles[1:]  # every participant except the caller, same order


def test_shares_sum_exactly_to_amount():
    """R-1-172, R-1-004"""
    fixture, handles, tokens = _n_user_fixture(7)
    r = api_post("/splits", json={"amount": 1000, "participant_handles": handles},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    shares = r.json()["shares"]
    assert sum(s["amount"] for s in shares) == 1000


@pytest.mark.parametrize("amount,n,expected", [
    (1000, 3, [334, 333, 333]),
    (1, 3, [1, 0, 0]),
    (10, 3, [4, 3, 3]),
    (999, 3, [333, 333, 333]),
    (5, 5, [1, 1, 1, 1, 1]),
    (17, 5, [4, 4, 3, 3, 3]),  # rem=2: pins the boundary between the 2nd and
                               # 3rd participant (every rem=1 case above only
                               # exercises a single `i < rem` boundary; this
                               # one needs two consecutive indices to get the
                               # extra unit and the third not to, so an
                               # off-by-one in the comparison can't hide)
])
def test_share_arithmetic_matches_spec_examples(amount, n, expected):
    """R-1-173, R-1-174"""
    fixture, handles, tokens = _n_user_fixture(n)
    r = api_post("/splits", json={"amount": amount, "participant_handles": handles},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    shares = r.json()["shares"]
    actual = [next(s["amount"] for s in shares if s["handle"] == handles[i]) for i in range(n)]
    assert actual == expected


def test_reordering_participants_changes_who_gets_extra_unit():
    """R-1-175"""
    fixture, handles, tokens = _n_user_fixture(3)
    r1 = api_post("/splits", json={"amount": 10, "participant_handles": handles},
                  headers={**auth(tokens[0]), **idem(unique("k1"))})
    shares1 = {s["handle"]: s["amount"] for s in r1.json()["shares"]}

    reordered = [handles[2], handles[1], handles[0]]
    r2 = api_post("/splits", json={"amount": 10, "participant_handles": reordered},
                  headers={**auth(tokens[0]), **idem(unique("k2"))})
    shares2 = {s["handle"]: s["amount"] for s in r2.json()["shares"]}

    assert shares1[handles[0]] == 4  # base=3 rem=1, first in original order gets the extra
    assert shares2[handles[2]] == 4  # first in reordered list gets the extra now


def test_zero_share_is_legal_and_still_creates_request():
    """R-1-175"""
    fixture, handles, tokens = _n_user_fixture(5)
    r = api_post("/splits", json={"amount": 1, "participant_handles": handles},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    shares = {s["handle"]: s["amount"] for s in r.json()["shares"]}
    zero_handles = [h for h, amt in shares.items() if amt == 0]
    assert zero_handles
    request_payer_handles = {req["payer_handle"] for req in r.json()["requests"]}
    for h in zero_handles:
        if h != handles[0]:
            assert h in request_payer_handles


def test_split_only_caller_participant():
    """R-1-176"""
    fixture, handles, tokens = _n_user_fixture(1)
    r = api_post("/splits", json={"amount": 100, "participant_handles": handles},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["shares"]) == 1
    assert body["shares"][0]["amount"] == 100
    assert body["requests"] == []


def test_split_checks_no_balance_and_moves_no_money():
    """R-1-177"""
    fixture, handles, tokens = _n_user_fixture(3, balance=0)
    r = api_post("/splits", json={"amount": 1_000_000, "participant_handles": handles},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    for t in tokens:
        assert api_get("/me", headers=auth(t)).json()["balance"] == 0


def test_split_errors():
    """R-1-178"""
    fixture, handles, tokens = _n_user_fixture(3)

    r = api_post("/splits", json={"amount": 0, "participant_handles": handles}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/splits", json={"amount": 10, "participant_handles": []}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/splits", json={"amount": 10, "participant_handles": [handles[0], handles[0]]},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/splits", json={"amount": 10, "participant_handles": handles, "note": "x" * 201},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/splits", json={"amount": 10, "participant_handles": [unique_handle("ghost")]},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 404, "not_found")


def test_split_participant_handles_type_errors():
    """R-1-179"""
    fixture, handles, tokens = _n_user_fixture(2)

    r = api_post("/splits", json={"amount": 10}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/splits", json={"amount": 10, "participant_handles": "not-an-array"},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")

    r = api_post("/splits", json={"amount": 10, "participant_handles": [handles[0], 42]},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 400, "malformed_request")

    r = api_post("/splits", json={"amount": 10, "participant_handles": [handles[0], "Not Valid!"]},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_each_split_independent_balances_sum_preserved():
    """R-1-180, R-1-001"""
    fixture, handles, tokens = _n_user_fixture(4, balance=1000)
    seeded_total = sum(u["balance"] for u in fixture["users"])

    for round_i in range(3):
        r = api_post("/splits", json={"amount": 100 + round_i, "participant_handles": handles},
                     headers={**auth(tokens[0]), **idem(unique(f"split{round_i}"))})
        assert r.status_code == 201, r.text
        for req in r.json()["requests"]:
            payer_idx = handles.index(req["payer_handle"])
            pay = api_post(f"/requests/{req['request_id']}/pay", json={},
                           headers={**auth(tokens[payer_idx]), **idem(unique(f"pay{round_i}-{payer_idx}"))})
            assert pay.status_code == 201, pay.text

    total = sum(api_get("/me", headers=auth(t)).json()["balance"] for t in tokens)
    assert total == seeded_total
