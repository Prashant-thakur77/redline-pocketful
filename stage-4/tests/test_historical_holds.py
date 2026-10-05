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

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       open_authorization, reset_ok, two_user_fixture, unique, unique_handle, user)


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
    as_of instant taken before the void.

    The open and the as_of check must sit at fixed, known instants with a
    real gap from the (live) void call, never derived from now() under
    latency: the original version computed mid = now()+50ms BEFORE calling
    void(), assuming that gave headroom before the void landed — but the
    void round-trip finishes in single-digit ms, so mid (the LATER of the
    two timestamps) actually landed after the void, not before it. Seeding
    the authorization with an explicit past created_at (R-3-119/120 allow
    it) puts open and mid an hour in the past, comfortably before the live
    void call's real "now" — no race."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    auth_id = unique("a")
    created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    fixture = make_fixture(
        [user(a_id, a_handle, balance=5000), user(b_id, b_handle, balance=0)],
        authorizations=[{"id": auth_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 1000,
                          "note": "", "visibility": "public", "status": "open",
                          "expires_at": _iso(created_at + timedelta(hours=2)),
                          "created_at": _iso(created_at)}],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    mid = created_at + timedelta(minutes=5)

    voided = api_post(f"/authorizations/{auth_id}/void", json={}, headers=auth(token_a))
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


def test_seeded_authorization_created_at_honored():
    """R-3-119, R-3-120: a seeded open authorization's created_at, supplied
    and not later than reset time or its own expires_at, must be used
    verbatim as its created_at — not silently replaced with reset time.
    Found while repairing test_as_of_between_open_and_void_still_shows_held
    (N3-T.8): the export of a freshly seeded authorization showed
    created_at ~= reset time regardless of what was supplied."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    auth_id = unique("a")
    created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    fixture = make_fixture(
        [user(a_id, a_handle, balance=5000), user(b_id, b_handle, balance=0)],
        authorizations=[{"id": auth_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 1000,
                          "note": "", "visibility": "public", "status": "open",
                          "expires_at": _iso(created_at + timedelta(hours=2)),
                          "created_at": _iso(created_at)}],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])

    listed = api_get("/authorizations", headers=auth(token_a), params={"limit": 50}).json()
    match = next(a for a in listed["authorizations"] if a["authorization_id"] == auth_id)
    assert match["created_at"] == _iso(created_at), \
        f"seeded created_at must be used verbatim, got {match['created_at']!r} vs supplied {_iso(created_at)!r}"


def test_seeded_authorization_created_at_after_reset_time_rejected_422():
    """R-3-120: a seeded created_at later than reset time is
    422 validation_failed from reset, with prior state left intact."""
    keep_id = unique("u")
    keep = make_fixture([user(keep_id, unique_handle("keep"), balance=321)])
    reset_ok(keep)
    token = login_token(keep["users"][0]["email"])

    a_id, b_id = unique("u"), unique("u")
    future_created_at = datetime.now(timezone.utc) + timedelta(hours=1)
    bad = make_fixture(
        [user(a_id, unique_handle("a"), balance=5000), user(b_id, unique_handle("b"), balance=0)],
        authorizations=[{"id": unique("a"), "from_user_id": a_id, "to_user_id": b_id, "amount": 1000,
                          "note": "", "visibility": "public", "status": "open",
                          "expires_at": _iso(future_created_at + timedelta(hours=2)),
                          "created_at": _iso(future_created_at)}],
    )
    r = api_post("/_test/reset", json=bad)
    assert_error(r, 422, "validation_failed")

    still = api_get("/me", headers=auth(token))
    assert still.status_code == 200
    assert still.json()["balance"] == 321


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
