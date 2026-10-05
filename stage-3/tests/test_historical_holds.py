"""Bitemporal views of holds: R-3-110..120.

GET /me?as_of must report `held`/`available` as they stood at that
effective instant, not the current snapshot — an authorization opened
after `as_of` must not count, one voided/captured after `as_of` must still
count as held at that instant, and `available` must still equal
`balance - held` in every such view (R-2-002's invariant survives into the
bitemporal views, it doesn't relax there).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, open_authorization, two_user_fixture, unique


def _iso(dt):
    return dt.isoformat()


def _me_as_of(token, as_of):
    r = api_get("/me", headers=auth(token), params={"as_of": _iso(as_of)})
    assert r.status_code == 200, r.text
    return r.json()


def test_as_of_before_hold_opened_shows_zero_held():
    """R-3-110"""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    before = datetime.now(timezone.utc)
    open_authorization(token_a, b_handle, amount=1000)

    view = _me_as_of(token_a, before)
    assert view.get("held", 0) == 0
    assert view["available"] == view["balance"]


def test_as_of_after_hold_opened_shows_held_and_consistent_available():
    """R-3-111"""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    open_authorization(token_a, b_handle, amount=1000)
    after = datetime.now(timezone.utc) + timedelta(seconds=1)

    view = _me_as_of(token_a, after)
    assert view["held"] == 1000
    assert view["available"] == view["balance"] - 1000


def test_as_of_between_open_and_void_still_shows_held():
    """R-3-112: a hold that was voided LATER must still show as held for an
    as_of instant taken before the void."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    hold = open_authorization(token_a, b_handle, amount=1000)
    mid = datetime.now(timezone.utc) + timedelta(milliseconds=50)

    voided = api_post(f"/authorizations/{hold['authorization_id']}/void", json={}, headers=auth(token_a))
    assert voided.status_code == 200, voided.text

    view = _me_as_of(token_a, mid)
    assert view["held"] == 1000, "an as_of before the void must still count the hold"


def test_as_of_after_void_shows_zero_held():
    """R-3-113"""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    hold = open_authorization(token_a, b_handle, amount=1000)
    voided = api_post(f"/authorizations/{hold['authorization_id']}/void", json={}, headers=auth(token_a))
    assert voided.status_code == 200, voided.text
    after = datetime.now(timezone.utc) + timedelta(seconds=1)

    view = _me_as_of(token_a, after)
    assert view.get("held", 0) == 0


def test_as_of_available_never_exceeds_balance_across_hold_lifecycle():
    """R-3-002, R-3-114: available <= balance at every as_of instant across
    open -> partial capture -> void/close."""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    hold = open_authorization(token_a, b_handle, amount=1000)
    t1 = datetime.now(timezone.utc) + timedelta(milliseconds=20)

    cap = api_post(f"/authorizations/{hold['authorization_id']}/capture", json={"amount": 400, "final": True},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text
    t2 = datetime.now(timezone.utc) + timedelta(milliseconds=20)

    for instant in (t1, t2):
        view = _me_as_of(token_a, instant)
        assert view["available"] <= view["balance"]
        assert view["available"] >= 0
