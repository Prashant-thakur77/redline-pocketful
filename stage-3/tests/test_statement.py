"""GET /statement: R-3-030..044.

ASSUMED CONTRACT (flagged for @planner/@builder to confirm): GET /statement
requires auth, returns 200 with {"entries": [...], "opening_balance": int,
"closing_balance": int, "snapshot_token": str|None, "has_more": bool}.
Each entry has at least {"payment_id": str, "amount": int (signed: positive
for money in, negative for money out), "effective_at": iso8601}. Entries
are ordered by effective_at ascending. `limit` bounds page size; a second
page is fetched by passing the previous page's `snapshot_token` back.
"""
from __future__ import annotations

from conftest import api_get, api_post, auth, idem, n_user_fixture, two_user_fixture, unique


def _statement(token, **params):
    r = api_get("/statement", headers=auth(token), params=params or None)
    assert r.status_code == 200, f"GET /statement failed: {r.status_code} {r.text}"
    return r.json()


def test_statement_requires_auth():
    """R-3-030"""
    r = api_get("/statement")
    assert r.status_code == 401, r.text


def test_statement_empty_for_a_fresh_user():
    """R-3-031"""
    fixture, token_a, _ = two_user_fixture()
    body = _statement(token_a)
    assert body["entries"] == []
    assert body["opening_balance"] == body["closing_balance"] == 10_000


def test_statement_lists_a_payment_as_a_signed_entry():
    """R-3-032, R-3-033: the payer's entry is negative, the receiver's is
    positive, for the same payment."""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 300},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    a_statement = _statement(token_a)
    b_statement = _statement(token_b)
    a_entry = next(e for e in a_statement["entries"] if e["payment_id"] == pay_id)
    b_entry = next(e for e in b_statement["entries"] if e["payment_id"] == pay_id)
    assert a_entry["amount"] == -300
    assert b_entry["amount"] == 300


def test_statement_entries_ordered_by_effective_at_ascending():
    """R-3-034"""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in (10, 20, 30):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    body = _statement(token_a)
    effective_times = [e["effective_at"] for e in body["entries"]]
    assert effective_times == sorted(effective_times)


def test_statement_opening_plus_deltas_equals_closing():
    """R-3-035: opening_balance + sum(entry amounts) == closing_balance, over
    the full (unwindowed) statement."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in (100, 250, 75):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    body = _statement(token_a)
    assert body["opening_balance"] + sum(e["amount"] for e in body["entries"]) == body["closing_balance"]
    assert body["closing_balance"] == 5000 - (100 + 250 + 75)


def test_statement_pagination_covers_every_entry_exactly_once():
    """R-3-036..039: walking every page via snapshot_token must yield every
    entry exactly once, in the same order the unpaginated call gives."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 8):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    full = _statement(token_a)
    assert len(full["entries"]) == 7

    paged_ids = []
    token = None
    for _ in range(10):
        page = _statement(token_a, **({"limit": 2, "snapshot_token": token} if token else {"limit": 2}))
        paged_ids += [e["payment_id"] for e in page["entries"]]
        if not page["has_more"]:
            break
        token = page["snapshot_token"]
    assert paged_ids == [e["payment_id"] for e in full["entries"]]


def test_statement_only_shows_the_authenticated_users_own_entries():
    """R-3-040"""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    _, _, _, tokens3 = n_user_fixture(3)
    outsider_statement = _statement(tokens3[2])
    assert outsider_statement["entries"] == []


def test_statement_limit_bounds_page_size():
    """R-3-041"""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 6):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    page = _statement(token_a, limit=2)
    assert len(page["entries"]) == 2
    assert page["has_more"] is True


def test_statement_invalid_limit_422():
    """R-3-042"""
    fixture, token_a, _ = two_user_fixture()
    r = api_get("/statement", headers=auth(token_a), params={"limit": -1})
    assert r.status_code == 422, r.text
    r2 = api_get("/statement", headers=auth(token_a), params={"limit": "abc"})
    assert r2.status_code == 422, r2.text
