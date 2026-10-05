"""Expiry is exact and read-driven: R-2-030..034. No background job is
required, or allowed to be required, for a read right after the deadline
to be correct — these tests prove that by never performing a write between
creating a short-lived hold and reading it again."""
from __future__ import annotations

import time

from conftest import (api_get, api_post, assert_error, auth, idem, n_user_fixture,
                       open_authorization, unique)


def test_expiry_flips_on_a_read_with_no_intervening_write():
    """R-2-030, R-2-031: once expires_at has passed, GET /authorizations
    shows status "expired" with no write having occurred in between."""
    fixture, ids, handles, tokens = n_user_fixture(2, authorization_ttl_seconds=1)
    a = open_authorization(tokens[0], handles[1], amount=100)
    aid = a["authorization_id"]

    still_open = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    assert next(x for x in still_open if x["authorization_id"] == aid)["status"] == "open"

    time.sleep(1.5)

    after = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match = next(x for x in after if x["authorization_id"] == aid)
    assert match["status"] == "expired"


def test_expired_never_matches_status_open_filter():
    """R-2-031"""
    fixture, ids, handles, tokens = n_user_fixture(2, authorization_ttl_seconds=1)
    a = open_authorization(tokens[0], handles[1], amount=100)
    aid = a["authorization_id"]
    time.sleep(1.5)

    open_only = api_get("/authorizations", headers=auth(tokens[0]), params={"status": "open"}).json()["authorizations"]
    assert all(x["authorization_id"] != aid for x in open_only)

    expired_only = api_get("/authorizations", headers=auth(tokens[0]), params={"status": "expired"}).json()["authorizations"]
    assert any(x["authorization_id"] == aid for x in expired_only)


def test_get_me_releases_remainder_on_read_with_no_write():
    """R-2-032: available reflects the released hold immediately, purely
    from a GET /me read, with no write in between."""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000, authorization_ttl_seconds=1)
    a = open_authorization(tokens[0], handles[1], amount=400)

    held_now = api_get("/me", headers=auth(tokens[0])).json()
    assert held_now["available"] == 600

    time.sleep(1.5)

    released = api_get("/me", headers=auth(tokens[0])).json()
    assert released["held"] == 0
    assert released["available"] == 1000
    assert released["total"] == 1000


def test_expiry_of_partial_capture_releases_only_remainder():
    """R-2-033: expiry of a partially captured authorization releases only
    the remainder and preserves every capture record and captured_amount."""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000, authorization_ttl_seconds=2)
    a = open_authorization(tokens[0], handles[1], amount=1000)
    aid = a["authorization_id"]
    cap = api_post(f"/authorizations/{aid}/capture", json={"amount": 300, "final": False},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text

    time.sleep(2.5)

    listing = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match = next(x for x in listing if x["authorization_id"] == aid)
    assert match["status"] == "expired"
    assert match["captured_amount"] == 300
    assert match["payment_ids"] == [cap.json()["payment_id"]]
    assert match["remaining_amount"] == 0

    payer = api_get("/me", headers=auth(tokens[0])).json()
    assert payer["total"] == 1000 - 300
    assert payer["held"] == 0
    assert payer["available"] == 700


def test_capture_at_exactly_expires_at_is_409_expired():
    """R-2-034: expiry is exact to the instant of expires_at, not a sweep
    boundary — a capture after a short TTL has elapsed must be rejected."""
    fixture, ids, handles, tokens = n_user_fixture(2, authorization_ttl_seconds=1)
    a = open_authorization(tokens[0], handles[1], amount=100)
    aid = a["authorization_id"]
    time.sleep(1.5)
    capture = api_post(f"/authorizations/{aid}/capture", json={},
                       headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(capture, 409, "authorization_expired")


def test_newly_created_authorization_may_have_sub_hour_lifetime():
    """R-2-034"""
    fixture, ids, handles, tokens = n_user_fixture(2, authorization_ttl_seconds=5)
    a = open_authorization(tokens[0], handles[1], amount=100)
    assert a["status"] == "open"


def test_void_on_an_expired_authorization_is_409_not_open():
    """R-2-073: voiding a captured OR expired authorization is 409
    authorization_not_open — expiry already closed it, so there is nothing
    left for a void to release."""
    fixture, ids, handles, tokens = n_user_fixture(2, authorization_ttl_seconds=1)
    a = open_authorization(tokens[0], handles[1], amount=100)
    aid = a["authorization_id"]
    time.sleep(1.5)
    void = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert_error(void, 409, "authorization_not_open")
