"""Statement snapshot tokens — frozen pagination under concurrent writes:
R-3-080..091.

Builds on the same assumed GET /statement contract as test_statement.py.
The field/query-param name is "snapshot" (CONFIRMED by @planner, commit
900d36d, R-3-079). The point of a snapshot is stability: once a client has it, the
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


def test_snapshot_first_page_is_stable_across_later_writes():
    """R-3-080, R-3-081: a page fetched with a remembered snapshot token
    must be byte-for-byte identical before and after new payments land."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in (10, 20, 30):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    first = _statement(token_a, limit=2)
    token = first.get("snapshot")
    assert token, "a statement page must carry a 'snapshot' token to replay against"

    replay_before = _statement(token_a, limit=2, snapshot=token)
    assert replay_before == first

    new_pay = api_post("/payments", json={"to_handle": b_handle, "amount": 999},
                       headers={**auth(token_a), **idem(unique("k"))})
    assert new_pay.status_code == 201, new_pay.text

    replay_after = _statement(token_a, limit=2, snapshot=token)
    assert replay_after == first, "a snapshot-addressed page must not change after new writes"


def test_fresh_tokenless_call_sees_new_writes_immediately():
    """R-3-082: a plain (no snapshot) call always reflects the current
    ledger, unlike a snapshot-addressed replay."""
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


def test_walking_every_page_via_snapshot_stays_consistent_despite_writes():
    """R-3-083, R-3-084, R-3-092: a full page-walk started before new writes
    land must see the same total entry count throughout the walk, not a
    shifting total that drops or duplicates an entry because of concurrent
    inserts. The snapshot token stays constant for the whole walk — R-3-090
    requires it echoed unchanged — and `offset` is what advances a page
    (R-3-092); an earlier version of this test fed the returned token back
    with no offset, which under a correct (frozen) implementation just
    re-requests the first page forever, fixed per planner's ruling. The
    walk is capped so a non-advancing implementation fails this test
    instead of hanging the suite."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 6):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    first_page = _statement(token_a, limit=2)
    token = first_page["snapshot"]

    # a write that lands mid-walk must not perturb this already-started walk
    intruder = api_post("/payments", json={"to_handle": b_handle, "amount": 777},
                        headers={**auth(token_a), **idem(unique("k"))})
    assert intruder.status_code == 201, intruder.text

    walked = list(first_page["entries"])
    has_more = first_page["has_more"]
    offset = 2
    for _ in range(10):
        if not has_more:
            break
        page = _statement(token_a, limit=2, snapshot=token, offset=offset)
        assert page["snapshot"] == token, "the snapshot token must be echoed unchanged (R-3-090)"
        walked += page["entries"]
        has_more = page["has_more"]
        offset += 2
    else:
        assert False, "did not terminate within 10 pages advancing offset by limit"

    assert len(walked) == 5, f"a walk started before the intruding write must see exactly the original 5: {walked}"
    assert len({e["payment_id"] for e in walked}) == 5, "no duplicate entries across pages"


def test_unknown_or_foreign_or_stale_snapshot_token_404():
    """R-3-084: an unknown token, another user's token, or a token taken
    before a `POST /_test/reset`, all give 404 not_found. (An earlier
    version of this test asserted 422 for an unknown token and cited
    R-3-091, which is about PRECEDENCE — a foreign token's 404 outranks
    limit/offset validation — not the status code itself; fixed per
    planner's ruling.)"""
    fixture, token_a, token_b = two_user_fixture()

    r = api_get("/statement", headers=auth(token_a), params={"snapshot": "not-a-real-token"})
    assert r.status_code == 404, r.text

    own_token = _statement(token_a, limit=5)["snapshot"]
    assert own_token
    foreign = api_get("/statement", headers=auth(token_b), params={"snapshot": own_token})
    assert foreign.status_code == 404, foreign.text

    pre_reset_token = _statement(token_a, limit=5)["snapshot"]
    assert pre_reset_token
    _, new_token_a, _ = two_user_fixture()  # a fresh reset invalidates the old token
    stale = api_get("/statement", headers=auth(new_token_a), params={"snapshot": pre_reset_token})
    assert stale.status_code == 404, stale.text
