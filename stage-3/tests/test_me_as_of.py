"""Point-in-time balance views: R-3-020..027.

`as_of` selects the balance in EFFECTIVE time: the view a user's balance
would have shown if every revision recorded by now had instead been applied
exactly at its own effective_at, in effective_at order. It is driven purely
by each revision's effective_at/amount, independent of when corrections
were actually recorded.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, two_user_fixture, unique


def _iso(dt):
    return dt.isoformat()


def test_as_of_now_matches_plain_balance():
    """R-3-020: as_of defaulting to (or explicitly set to) now must agree
    with the plain, un-parameterized balance."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    plain = api_get("/me", headers=auth(token_a)).json()["balance"]
    now = datetime.now(timezone.utc)
    as_of_now = api_get("/me", headers=auth(token_a), params={"as_of": _iso(now)}).json()["balance"]
    assert as_of_now == plain == 4500


def test_as_of_before_a_payment_excludes_its_effect():
    """R-3-021: an as_of strictly before a payment's effective_at must show
    the balance as if that payment had not happened."""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    before = datetime.now(timezone.utc)
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    a_as_of_before = api_get("/me", headers=auth(token_a), params={"as_of": _iso(before)}).json()["balance"]
    b_as_of_before = api_get("/me", headers=auth(token_b), params={"as_of": _iso(before)}).json()["balance"]
    assert a_as_of_before == 5000
    assert b_as_of_before == 0


def test_as_of_reflects_a_backdated_correction():
    """R-3-022: a correction whose effective_at is backdated to before an
    as_of instant must change what that as_of view shows, even though the
    correction was RECORDED after the as_of instant passed."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    check_instant = datetime.now(timezone.utc)
    before_check = api_get("/me", headers=auth(token_b), params={"as_of": _iso(check_instant)}).json()["balance"]
    assert before_check == 100

    # a correction, recorded now, whose effective_at is backdated to just
    # before check_instant
    corr = api_post(f"/payments/{pay_id}/corrections",
                    json={"expected_revision": 1, "amount": 400,
                          "effective_at": _iso(check_instant - timedelta(seconds=1)),
                          "reason": "backdated"},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text

    after_check = api_get("/me", headers=auth(token_b), params={"as_of": _iso(check_instant)}).json()["balance"]
    assert after_check == 400, "a backdated correction must retroactively change an as_of view taken before it was recorded"


def test_as_of_future_instant_matches_current_state():
    """R-3-023: an as_of in the future (beyond any recorded revision's
    effective_at) must show the same thing as the current balance."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 200},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    future = datetime.now(timezone.utc) + timedelta(days=365)
    current = api_get("/me", headers=auth(token_a)).json()["balance"]
    far_future = api_get("/me", headers=auth(token_a), params={"as_of": _iso(future)}).json()["balance"]
    assert far_future == current == 4800


def test_as_of_malformed_timestamp_422():
    """R-3-024"""
    fixture, token_a, _ = two_user_fixture()
    r = api_get("/me", headers=auth(token_a), params={"as_of": "not-a-timestamp"})
    assert r.status_code == 422, r.text


def test_as_of_never_negative_across_two_corrections_at_different_instants():
    """R-3-027: two corrections with different effective_at values must
    each be independently reflected — as_of between them shows the first,
    as_of after shows the second, neither shows a negative balance."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    t1 = datetime.now(timezone.utc) + timedelta(seconds=1)
    c1 = api_post(f"/payments/{pay_id}/corrections",
                 json={"expected_revision": 1, "amount": 300, "effective_at": _iso(t1), "reason": "step1"},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert c1.status_code == 201, c1.text

    t2 = t1 + timedelta(seconds=1)
    c2 = api_post(f"/payments/{pay_id}/corrections",
                 json={"expected_revision": 2, "amount": 50, "effective_at": _iso(t2), "reason": "step2"},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert c2.status_code == 201, c2.text

    mid = t1 + timedelta(milliseconds=500)
    at_mid = api_get("/me", headers=auth(token_b), params={"as_of": _iso(mid)}).json()["balance"]
    assert at_mid == 300
    at_end = api_get("/me", headers=auth(token_b),
                     params={"as_of": _iso(t2 + timedelta(seconds=1))}).json()["balance"]
    assert at_end == 50
    assert at_mid >= 0 and at_end >= 0
