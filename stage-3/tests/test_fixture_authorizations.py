"""Fixture additions for holds: R-2-020..028."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import (api_get, api_post, assert_error, auth, authorization, idem, login_token,
                      make_fixture, reset, reset_ok, unique, unique_handle, user)


def _far_future() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()


def _far_past() -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def test_ttl_defaults_to_600_when_omitted():
    """R-2-020"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    r = api_post("/authorizations", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    created = datetime.fromisoformat(r.json()["created_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(r.json()["expires_at"].replace("Z", "+00:00"))
    assert (expires - created).total_seconds() == 600


def test_ttl_non_positive_or_non_integer_rejected_from_reset():
    """R-2-020"""
    a_id = unique("u")
    for bad_ttl in (0, -5, 10.5):
        fixture = make_fixture([user(a_id, unique_handle("a"), balance=10)], authorization_ttl_seconds=bad_ttl)
        r = reset(fixture)
        assert_error(r, 422, "validation_failed")


def test_authorizations_array_omitted_means_empty_stage1_fixture_valid():
    """R-2-021"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=1000), user(b_id, unique_handle("b"), balance=0)])
    r = reset(fixture)
    assert r.status_code == 204, r.text
    token_a = login_token(fixture["users"][0]["email"])
    listing = api_get("/authorizations", headers=auth(token_a))
    assert listing.status_code == 200
    assert listing.json()["authorizations"] == []


def test_seeded_authorization_has_absolute_expires_at():
    """R-2-022"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    auth_id = unique("a")
    expires = _far_future()
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)],
        authorizations=[authorization(auth_id, a_id, b_id, 500, status="open", expires_at=expires)],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    listing = api_get("/authorizations", headers=auth(token_a)).json()["authorizations"]
    match = next(x for x in listing if x["authorization_id"] == auth_id)
    assert match["expires_at"] == expires or match["expires_at"][:19] == expires[:19]


def test_seeded_balance_is_total_available_is_derived():
    """R-2-023"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    auth_id = unique("a")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)],
        authorizations=[authorization(auth_id, a_id, b_id, 300, status="open", expires_at=_far_future())],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    me = api_get("/me", headers=auth(token_a)).json()
    assert me["balance"] == me["total"] == 1000
    assert me["held"] == 300
    assert me["available"] == 700


def test_seeded_open_holds_exceeding_balance_rejected():
    """R-2-024"""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100), user(b_id, unique_handle("b"), balance=0),
         user(c_id, unique_handle("c"), balance=0)],
        authorizations=[
            authorization(unique("a"), a_id, b_id, 60, status="open", expires_at=_far_future()),
            authorization(unique("a"), a_id, c_id, 60, status="open", expires_at=_far_future()),
        ],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_seeded_bad_status_rejected():
    """R-2-025"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100), user(b_id, unique_handle("b"), balance=0)],
        authorizations=[authorization(unique("a"), a_id, b_id, 50, status="not-a-status", expires_at=_far_future())],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_seeded_open_but_past_expiry_holds_nothing_reads_expired():
    """R-2-026"""
    a_id, b_id = unique("u"), unique("u")
    auth_id = unique("a")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=1000), user(b_id, unique_handle("b"), balance=0)],
        authorizations=[authorization(auth_id, a_id, b_id, 400, status="open", expires_at=_far_past())],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    me = api_get("/me", headers=auth(token_a)).json()
    assert me["held"] == 0
    assert me["available"] == 1000
    listing = api_get("/authorizations", headers=auth(token_a)).json()["authorizations"]
    match = next(x for x in listing if x["authorization_id"] == auth_id)
    assert match["status"] == "expired"


def test_seeded_authorization_unknown_user_rejected():
    """R-2-027"""
    a_id = unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100)],
        authorizations=[authorization(unique("a"), a_id, "no-such-user", 50, status="open", expires_at=_far_future())],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_seeded_authorization_self_reference_rejected():
    """R-2-027"""
    a_id = unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=100)],
        authorizations=[authorization(unique("a"), a_id, a_id, 50, status="open", expires_at=_far_future())],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")


def test_seeded_captured_amount_defaults():
    """R-2-028"""
    a_id, b_id = unique("u"), unique("u")
    open_id, voided_id, captured_id = unique("a"), unique("a"), unique("a")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=1000), user(b_id, unique_handle("b"), balance=0)],
        authorizations=[
            authorization(open_id, a_id, b_id, 100, status="open", expires_at=_far_future()),
            authorization(voided_id, a_id, b_id, 100, status="voided", expires_at=_far_future()),
            authorization(captured_id, a_id, b_id, 250, status="captured", expires_at=_far_future()),
        ],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    listing = api_get("/authorizations", headers=auth(token_a)).json()["authorizations"]
    by_id = {x["authorization_id"]: x for x in listing}
    assert by_id[open_id]["captured_amount"] == 0
    assert by_id[voided_id]["captured_amount"] == 0
    assert by_id[captured_id]["captured_amount"] == 250


def test_seeded_captured_amount_out_of_range_rejected():
    """R-2-028"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture(
        [user(a_id, unique_handle("a"), balance=1000), user(b_id, unique_handle("b"), balance=0)],
        authorizations=[authorization(unique("a"), a_id, b_id, 100, status="captured",
                                       expires_at=_far_future(), captured_amount=101)],
    )
    r = reset(fixture)
    assert_error(r, 422, "validation_failed")

    fixture2 = make_fixture(
        [user(a_id, unique_handle("a2"), balance=1000), user(b_id, unique_handle("b2"), balance=0)],
        authorizations=[authorization(unique("a"), a_id, b_id, 100, status="captured",
                                       expires_at=_far_future(), captured_amount=-1)],
    )
    r2 = reset(fixture2)
    assert_error(r2, 422, "validation_failed")
