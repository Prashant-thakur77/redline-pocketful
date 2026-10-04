"""Adversarial findings against N1-7 (POST /splits)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, login_token,  # noqa: E402
                      make_fixture, reset_ok, unique, unique_handle, user)


def _users(balances: dict):
    specs = {}
    for label, bal in balances.items():
        uid, handle = unique("u"), unique_handle(label[:3])
        email = f"{handle}@example.com"
        specs[label] = {"id": uid, "handle": handle, "email": email, "balance": bal}
    reset_ok(make_fixture([user(s["id"], s["handle"], balance=s["balance"], email=s["email"])
                            for s in specs.values()]))
    return {label: {**s, "token": login_token(s["email"])} for label, s in specs.items()}


def _split(token, amount, handles, note=None, key=None):
    body = {"amount": amount, "participant_handles": handles}
    if note is not None:
        body["note"] = note
    return api_post("/splits", json=body, headers=auth_idem(token, key or unique("split")))


@pytest.mark.parametrize("amount,n,expected", [
    (1000, 3, [334, 333, 333]),
    (1, 3, [1, 0, 0]),
    (10, 3, [4, 3, 3]),
    (999, 3, [333, 333, 333]),
    (5, 5, [1, 1, 1, 1, 1]),
])
def test_share_arithmetic_matches_spec_examples(amount, n, expected):
    """R-1-174: the rule reproduces every one of the spec's five examples
    exactly, for the caller alone (no requests created, just checking
    the share math)."""
    balances = {f"p{i}": 0 for i in range(n)}
    u = _users(balances)
    caller = u["p0"]
    handles = [u[f"p{i}"]["handle"] for i in range(n)]

    r = _split(caller["token"], amount, handles)
    assert r.status_code == 201, r.text
    shares = [s["amount"] for s in r.json()["shares"]]
    assert shares == expected, f"amount={amount} n={n}: expected {expected}, got {shares}"
    assert sum(shares) == amount, f"R-1-172: shares must sum exactly to amount, got {sum(shares)} != {amount}"


def test_reordering_participants_changes_who_gets_the_extra_unit():
    """R-1-175: reordering participant_handles gives the extra unit to a
    different participant — the larger shares go to whoever is listed
    first, not to a fixed identity."""
    u = _users({"a": 0, "b": 0, "c": 0})
    handles = [u["a"]["handle"], u["b"]["handle"], u["c"]["handle"]]

    r1 = _split(u["a"]["token"], 10, handles)
    shares1 = {s["handle"]: s["amount"] for s in r1.json()["shares"]}

    reordered = [u["c"]["handle"], u["b"]["handle"], u["a"]["handle"]]
    r2 = _split(u["a"]["token"], 10, reordered)
    shares2 = {s["handle"]: s["amount"] for s in r2.json()["shares"]}

    assert shares1[u["a"]["handle"]] == 4, shares1
    assert shares2[u["c"]["handle"]] == 4, shares2
    assert shares2[u["a"]["handle"]] == 3, shares2


def test_zero_share_is_legal_and_still_creates_a_request():
    """R-1-175: a share of 0 is legal and still produces a request for
    that participant — not silently skipped."""
    u = _users({"a": 0, "b": 0, "c": 0})
    # amount=1 across 3 participants: shares [1, 0, 0] (R-1-174's example),
    # so participants 2 and 3 get a zero share.
    handles = [u["a"]["handle"], u["b"]["handle"], u["c"]["handle"]]
    r = _split(u["a"]["token"], 1, handles)
    assert r.status_code == 201, r.text
    body = r.json()
    zero_share_handles = {s["handle"] for s in body["shares"] if s["amount"] == 0}
    assert zero_share_handles == {u["b"]["handle"], u["c"]["handle"]}

    request_handles_with_zero = [req["payer_handle"] for req in body["requests"]
                                  if req["amount"] == 0]
    assert set(request_handles_with_zero) == zero_share_handles, (
        f"a zero share must still create a request, got requests for {request_handles_with_zero}, "
        f"expected one each for {zero_share_handles}"
    )


def test_caller_only_split_creates_zero_requests():
    """R-1-176: a split whose only participant is the caller is valid: one
    share, zero requests, "requests": []."""
    u = _users({"a": 0})
    r = _split(u["a"]["token"], 500, [u["a"]["handle"]])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["requests"] == []
    assert body["shares"] == [{"handle": u["a"]["handle"], "amount": 500}]


def test_split_moves_no_money():
    """R-1-177: nothing about a split checks any balance, and a split
    moves no money — balances before and after must be identical."""
    u = _users({"a": 0, "b": 0, "c": 0})
    bal_before = {label: api_get("/me", headers=auth(u[label]["token"])).json()["balance"]
                  for label in ("a", "b", "c")}

    r = _split(u["a"]["token"], 999_999_999, [u["a"]["handle"], u["b"]["handle"], u["c"]["handle"]])
    assert r.status_code == 201, r.text

    bal_after = {label: api_get("/me", headers=auth(u[label]["token"])).json()["balance"]
                 for label in ("a", "b", "c")}
    assert bal_before == bal_after, f"a split must move no money: {bal_before} != {bal_after}"


def test_duplicate_participant_handle_is_422():
    """R-1-178: participant_handles containing a duplicate handle is 422."""
    u = _users({"a": 0, "b": 0})
    r = _split(u["a"]["token"], 100, [u["b"]["handle"], u["b"]["handle"]])
    assert_error(r, 422, "validation_failed")


def test_empty_participant_handles_is_422():
    """R-1-178: participant_handles empty is 422."""
    u = _users({"a": 0})
    r = _split(u["a"]["token"], 100, [])
    assert_error(r, 422, "validation_failed")


def test_unknown_handle_in_split_is_404():
    """R-1-178: any unknown handle is 404."""
    u = _users({"a": 0})
    r = _split(u["a"]["token"], 100, [u["a"]["handle"], "nosuchhandle0000"])
    assert_error(r, 404, "not_found")


def test_r_1_180_conservation_holds_after_many_splits_paid_in_full():
    """R-1-180: each split's shares are computed independently of every
    previous split; after any number of splits have been paid in full,
    balances still sum exactly to the seeded total — the only split
    property a storm can actually break."""
    u = _users({"caller": 0, "p0": 10_000, "p1": 10_000, "p2": 10_000})
    total = sum(spec["balance"] for spec in u.values())
    handles = [u["p0"]["handle"], u["p1"]["handle"], u["p2"]["handle"]]

    for amount in (1000, 1, 10, 999, 7):
        r = _split(u["caller"]["token"], amount, handles, key=unique(f"split-{amount}"))
        assert r.status_code == 201, r.text
        for req in r.json()["requests"]:
            payer_label = next(label for label, spec in u.items() if spec["handle"] == req["payer_handle"])
            payer_token = u[payer_label]["token"]
            pay = api_post(f"/requests/{req['request_id']}/pay", json={},
                            headers=auth_idem(payer_token, unique(f"pay-{req['request_id']}")))
            assert pay.status_code == 201, pay.text

    final_total = sum(api_get("/me", headers=auth(u[label]["token"])).json()["balance"] for label in u)
    assert final_total == total, f"conservation violated: {final_total} != {total}"
