"""Statement snapshot tokens — frozen pagination under concurrent writes:
R-3-080..091.

Builds on the same assumed GET /statement contract as test_statement.py.
The point of a snapshot token is stability: once a client has it, the
pages addressed through it must keep returning exactly what existed at the
instant the first page was taken, even if the underlying ledger gains new
entries in the meantime — a fresh (tokenless) call, by contrast, must see
the new entries immediately.
"""
from __future__ import annotations

from conftest import api_get, api_post, auth, idem, two_user_fixture, unique


def _statement(token, **params):
    r = api_get("/statement", headers=auth(token), params=params or None)
    assert r.status_code == 200, f"GET /statement failed: {r.status_code} {r.text}"
    return r.json()


def test_snapshot_token_first_page_is_stable_across_later_writes():
    """R-3-080, R-3-081: a page fetched with a remembered snapshot_token
    must be byte-for-byte identical before and after new payments land."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in (10, 20, 30):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    first = _statement(token_a, limit=2)
    token = first.get("snapshot_token")
    assert token, "a statement page must carry a snapshot_token to replay against"

    replay_before = _statement(token_a, limit=2, snapshot_token=token)
    assert replay_before == first

    new_pay = api_post("/payments", json={"to_handle": b_handle, "amount": 999},
                       headers={**auth(token_a), **idem(unique("k"))})
    assert new_pay.status_code == 201, new_pay.text

    replay_after = _statement(token_a, limit=2, snapshot_token=token)
    assert replay_after == first, "a snapshot_token page must not change after new writes"


def test_fresh_tokenless_call_sees_new_writes_immediately():
    """R-3-082: a plain (no snapshot_token) call always reflects the
    current ledger, unlike a token-addressed replay."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    before = _statement(token_a)
    assert before["entries"] == []

    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 42},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    after = _statement(token_a)
    assert len(after["entries"]) == 1
    assert after["entries"][0]["payment_id"] == pay.json()["payment_id"]


def test_walking_every_page_via_snapshot_token_stays_consistent_despite_writes():
    """R-3-083, R-3-084: a full page-walk started before new writes land
    must see the same total entry count throughout the walk, not a
    shifting total that drops or duplicates an entry because of
    concurrent inserts."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 6):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    first_page = _statement(token_a, limit=2)
    token = first_page["snapshot_token"]

    # a write that lands mid-walk must not perturb this already-started walk
    intruder = api_post("/payments", json={"to_handle": b_handle, "amount": 777},
                        headers={**auth(token_a), **idem(unique("k"))})
    assert intruder.status_code == 201, intruder.text

    walked = list(first_page["entries"])
    while first_page["has_more"]:
        first_page = _statement(token_a, limit=2, snapshot_token=token)
        walked += first_page["entries"]
        token = first_page.get("snapshot_token") or token

    assert len(walked) == 5, f"a walk started before the intruding write must see exactly the original 5: {walked}"
    assert len({e["payment_id"] for e in walked}) == 5, "no duplicate entries across pages"


def test_invalid_snapshot_token_422():
    """R-3-091"""
    fixture, token_a, _ = two_user_fixture()
    r = api_get("/statement", headers=auth(token_a), params={"snapshot_token": "not-a-real-token"})
    assert r.status_code == 422, r.text
