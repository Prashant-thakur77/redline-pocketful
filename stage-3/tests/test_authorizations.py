"""Authorizations (holds): create R-2-040..046, capture R-2-050..066,
void R-2-070..075, list R-2-080..084."""
from __future__ import annotations

import pytest

from conftest import (api_get, api_post, assert_error, auth, idem, n_user_fixture,
                       open_authorization, two_user_fixture, unique, unique_handle)


# ---------------------------------------------------------------------------
# POST /authorizations — R-2-040..046
# ---------------------------------------------------------------------------

def test_authorization_requires_key_and_shape():
    """R-2-040, R-2-041"""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]

    no_key = api_post("/authorizations", json={"to_handle": b_handle, "amount": 100}, headers=auth(token_a))
    assert_error(no_key, 400, "missing_idempotency_key")

    r = api_post("/authorizations", json={"to_handle": b_handle, "amount": 100},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    expected = {"authorization_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                "amount", "captured_amount", "currency", "note", "visibility", "status",
                "expires_at", "payment_id", "created_at", "remaining_amount", "payment_ids", "closed_at"}
    assert expected <= set(body.keys())
    assert body["captured_amount"] == 0
    assert body["status"] == "open"
    assert body["payment_id"] is None
    assert body["payment_ids"] == []
    assert body["remaining_amount"] == body["amount"] == 100
    assert body["closed_at"] is None
    assert body["note"] == ""
    assert body["visibility"] == "public"


def test_authorization_expires_at_is_created_at_plus_ttl():
    """R-2-042"""
    import datetime
    fixture, token_a, _ = two_user_fixture(authorization_ttl_seconds=120)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/authorizations", json={"to_handle": b_handle, "amount": 100},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    created = datetime.datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
    expires = datetime.datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
    assert (expires - created).total_seconds() == 120


def test_authorization_places_hold_not_transfer():
    """R-2-043"""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/authorizations", json={"to_handle": b_handle, "amount": 400},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text

    payer = api_get("/me", headers=auth(token_a)).json()
    assert payer["total"] == 1000
    assert payer["held"] == 400
    assert payer["available"] == 600

    receiver = api_get("/me", headers=auth(token_b)).json()
    assert receiver["total"] == 0
    assert receiver["held"] == 0
    assert receiver["available"] == 0


def test_authorization_insufficient_available_409():
    """R-2-044"""
    fixture, token_a, _ = two_user_fixture(balance_a=500, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    first = api_post("/authorizations", json={"to_handle": b_handle, "amount": 400},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert first.status_code == 201, first.text
    second = api_post("/authorizations", json={"to_handle": b_handle, "amount": 200},
                      headers={**auth(token_a), **idem(unique("k"))})
    assert_error(second, 409, "insufficient_funds")


def test_authorization_field_errors():
    """R-2-045"""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    own_handle = fixture["users"][0]["handle"]

    for amount in (0, -1, 1_000_000_001, 10.5):
        r = api_post("/authorizations", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert_error(r, 422, "validation_failed")

    self_auth = api_post("/authorizations", json={"to_handle": own_handle, "amount": 100},
                         headers={**auth(token_a), **idem(unique("k"))})
    assert_error(self_auth, 422, "self_payment")

    long_note = api_post("/authorizations", json={"to_handle": b_handle, "amount": 100, "note": "x" * 201},
                         headers={**auth(token_a), **idem(unique("k"))})
    assert_error(long_note, 422, "validation_failed")

    bad_vis = api_post("/authorizations", json={"to_handle": b_handle, "amount": 100, "visibility": "nope"},
                       headers={**auth(token_a), **idem(unique("k"))})
    assert_error(bad_vis, 422, "validation_failed")

    unknown = api_post("/authorizations", json={"to_handle": unique_handle("ghost"), "amount": 100},
                       headers={**auth(token_a), **idem(unique("k"))})
    assert_error(unknown, 404, "not_found")


def test_authorization_required_fields_missing_one_at_a_time():
    """R-2-040, R-2-045: gate-6 gap — every existing field-error test supplies
    both required fields with a bad VALUE; none omits exactly one field while
    leaving the other valid, which is what actually exercises a flipped
    `or`/`and` on the presence check in routes/authorizations.py."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]

    missing_to_handle = api_post("/authorizations", json={"amount": 100},
                                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(missing_to_handle, 422, "validation_failed")

    missing_amount = api_post("/authorizations", json={"to_handle": b_handle},
                              headers={**auth(token_a), **idem(unique("k"))})
    assert_error(missing_amount, 422, "validation_failed")

    missing_both = api_post("/authorizations", json={}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(missing_both, 422, "validation_failed")


def test_open_authorization_not_in_activity_feed():
    """R-2-046"""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/authorizations", json={"to_handle": b_handle, "amount": 100},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    feed = api_get("/activity", headers=auth(token_a))
    assert feed.json()["payments"] == []


# ---------------------------------------------------------------------------
# POST /authorizations/{id}/capture — R-2-050..066
# ---------------------------------------------------------------------------


def test_capture_requires_key_and_only_receiver():
    """R-2-050"""
    fixture, ids, handles, tokens = n_user_fixture(3)
    auth_obj = open_authorization(tokens[0], handles[1])
    aid = auth_obj["authorization_id"]

    no_key = api_post(f"/authorizations/{aid}/capture", json={}, headers=auth(tokens[1]))
    assert_error(no_key, 400, "missing_idempotency_key")

    not_receiver = api_post(f"/authorizations/{aid}/capture", json={},
                            headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(not_receiver, 403, "forbidden")

    third_party = api_post(f"/authorizations/{aid}/capture", json={},
                           headers={**auth(tokens[2]), **idem(unique("k"))})
    assert_error(third_party, 403, "forbidden")


def test_capture_defaults_amount_to_remainder_final_to_true():
    """R-2-051, R-2-056"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=700)
    aid = auth_obj["authorization_id"]
    r = api_post(f"/authorizations/{aid}/capture", json={}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    payment = r.json()
    assert payment["amount"] == 700


def test_capture_replay_requires_identical_body():
    """R-2-052"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=2000)
    aid = auth_obj["authorization_id"]
    key = unique("k")
    first = api_post(f"/authorizations/{aid}/capture", json={}, headers={**auth(tokens[1]), **idem(key)})
    assert first.status_code == 201, first.text
    second = api_post(f"/authorizations/{aid}/capture", json={"amount": 2000},
                      headers={**auth(tokens[1]), **idem(key)})
    assert_error(second, 409, "idempotency_key_reuse")


def test_capture_body_equality_is_type_strict_on_final():
    """R-2-063: the new fields do not change how body equality works —
    it is still the parsed JSON value (R-1-106), type-strict, so
    {"final": false} and {"final": 0} are different bodies even though a
    server might coerce 0 to falsy."""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    key = unique("k")
    first = api_post(f"/authorizations/{aid}/capture", json={"amount": 100, "final": False},
                     headers={**auth(tokens[1]), **idem(key)})
    assert first.status_code == 201, first.text
    second = api_post(f"/authorizations/{aid}/capture", json={"amount": 100, "final": 0},
                      headers={**auth(tokens[1]), **idem(key)})
    assert_error(second, 409, "idempotency_key_reuse")


def test_capture_response_shape_and_feed_visibility():
    """R-2-053, R-2-054"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=500, note="dinner", visibility="private")
    aid = auth_obj["authorization_id"]
    r = api_post(f"/authorizations/{aid}/capture", json={"amount": 300, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    payment = r.json()
    expected = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                "amount", "currency", "note", "visibility", "request_id", "created_at",
                "settlement_id", "authorization_id"}
    assert expected <= set(payment.keys())
    assert payment["authorization_id"] == aid
    assert payment["request_id"] is None
    assert payment["amount"] == 300
    assert payment["note"] == "dinner"
    assert payment["visibility"] == "private"

    sender_feed = api_get("/activity", headers=auth(tokens[0])).json()["payments"]
    receiver_feed = api_get("/activity", headers=auth(tokens[1])).json()["payments"]
    assert any(p["payment_id"] == payment["payment_id"] for p in sender_feed)
    assert any(p["payment_id"] == payment["payment_id"] for p in receiver_feed)


def test_capture_moves_money_and_reduces_hold_atomically():
    """R-2-055"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=600)
    aid = auth_obj["authorization_id"]

    payer_before = api_get("/me", headers=auth(tokens[0])).json()
    assert payer_before["total"] == 1000 and payer_before["held"] == 600 and payer_before["available"] == 400

    r = api_post(f"/authorizations/{aid}/capture", json={"amount": 250, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text

    payer_after = api_get("/me", headers=auth(tokens[0])).json()
    receiver_after = api_get("/me", headers=auth(tokens[1])).json()
    assert payer_after["total"] == 750
    assert payer_after["held"] == 350
    assert payer_after["available"] == 400
    assert receiver_after["total"] == 1250


def test_final_capture_releases_remainder_and_closes():
    """R-2-056"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=3000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=2000)
    aid = auth_obj["authorization_id"]

    r = api_post(f"/authorizations/{aid}/capture", json={"amount": 1500},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text

    payer = api_get("/me", headers=auth(tokens[0])).json()
    assert payer["total"] == 3000 - 1500
    assert payer["held"] == 0
    assert payer["available"] == payer["total"]

    listing = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match = next(a for a in listing if a["authorization_id"] == aid)
    assert match["status"] == "captured"
    assert match["captured_amount"] == 1500
    assert match["payment_id"] is not None
    assert match["remaining_amount"] == 0
    assert match["closed_at"] is not None


def test_second_capture_after_final_409():
    """R-2-057"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=500)
    aid = auth_obj["authorization_id"]
    first = api_post(f"/authorizations/{aid}/capture", json={}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert first.status_code == 201, first.text
    second = api_post(f"/authorizations/{aid}/capture", json={"amount": 1},
                      headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(second, 409, "authorization_not_open")


def test_partial_capture_stays_open_allows_further_captures():
    """R-2-058"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    r1 = api_post(f"/authorizations/{aid}/capture", json={"amount": 300, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r1.status_code == 201, r1.text
    listing = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match = next(a for a in listing if a["authorization_id"] == aid)
    assert match["status"] == "open"
    assert match["remaining_amount"] == 700

    r2 = api_post(f"/authorizations/{aid}/capture", json={"amount": 200, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r2.status_code == 201, r2.text


def test_capturing_exact_remainder_closes_even_with_final_false():
    """R-2-059"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=400)
    aid = auth_obj["authorization_id"]
    r = api_post(f"/authorizations/{aid}/capture", json={"amount": 400, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    listing = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match = next(a for a in listing if a["authorization_id"] == aid)
    assert match["status"] == "captured"
    assert match["remaining_amount"] == 0


def test_capture_exceeds_remainder_not_original_amount():
    """R-2-060"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    r1 = api_post(f"/authorizations/{aid}/capture", json={"amount": 600, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r1.status_code == 201, r1.text
    over_remainder = api_post(f"/authorizations/{aid}/capture", json={"amount": 500},
                              headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(over_remainder, 422, "capture_exceeds_authorization")
    exactly_remainder = api_post(f"/authorizations/{aid}/capture", json={"amount": 400},
                                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert exactly_remainder.status_code == 201, exactly_remainder.text


def test_capture_default_amount_never_triggers_exceeds():
    """R-2-060"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    api_post(f"/authorizations/{aid}/capture", json={"amount": 999, "final": False},
             headers={**auth(tokens[1]), **idem(unique("k"))})
    r = api_post(f"/authorizations/{aid}/capture", json={}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert r.json()["amount"] == 1


def test_captured_amount_cumulative_payment_ids_in_order_remaining_zero_when_closed():
    """R-2-061"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    r1 = api_post(f"/authorizations/{aid}/capture", json={"amount": 300, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k1"))})
    r2 = api_post(f"/authorizations/{aid}/capture", json={"amount": 400, "final": False},
                 headers={**auth(tokens[1]), **idem(unique("k2"))})
    assert r1.status_code == 201 and r2.status_code == 201

    listing = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match = next(a for a in listing if a["authorization_id"] == aid)
    assert match["captured_amount"] == 700
    assert match["payment_ids"] == [r1.json()["payment_id"], r2.json()["payment_id"]]
    assert match["payment_id"] == r2.json()["payment_id"]
    assert match["status"] == "open"
    assert match["remaining_amount"] == 300

    final = api_post(f"/authorizations/{aid}/capture", json={"amount": 300},
                     headers={**auth(tokens[1]), **idem(unique("k3"))})
    assert final.status_code == 201
    listing2 = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    match2 = next(a for a in listing2 if a["authorization_id"] == aid)
    assert match2["remaining_amount"] == 0
    assert match2["status"] == "captured"


def test_capture_errors_and_precedence():
    """R-2-064"""
    fixture, ids, handles, tokens = n_user_fixture(3)
    auth_obj = open_authorization(tokens[0], handles[1], amount=500)
    aid = auth_obj["authorization_id"]

    unknown = api_post("/authorizations/does-not-exist/capture", json={},
                       headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(unknown, 404, "not_found")

    not_receiver = api_post(f"/authorizations/{aid}/capture", json={},
                            headers={**auth(tokens[2]), **idem(unique("k"))})
    assert_error(not_receiver, 403, "forbidden")

    bad_amount = api_post(f"/authorizations/{aid}/capture", json={"amount": 0},
                          headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(bad_amount, 422, "validation_failed")

    bad_final = api_post(f"/authorizations/{aid}/capture", json={"final": "yes"},
                         headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(bad_final, 422, "validation_failed")

    exceeds = api_post(f"/authorizations/{aid}/capture", json={"amount": 999},
                       headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(exceeds, 422, "capture_exceeds_authorization")

    ok = api_post(f"/authorizations/{aid}/capture", json={"amount": 500},
                 headers={**auth(tokens[1]), **idem(unique("k"))})
    assert ok.status_code == 201, ok.text
    not_open = api_post(f"/authorizations/{aid}/capture", json={"amount": 1},
                        headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(not_open, 409, "authorization_not_open")


def test_capture_voided_is_not_open():
    """R-2-064, R-2-065"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=500)
    aid = auth_obj["authorization_id"]
    voided = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert voided.status_code == 200, voided.text
    capture = api_post(f"/authorizations/{aid}/capture", json={},
                       headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(capture, 409, "authorization_not_open")


def test_capture_never_fails_for_funds_even_at_zero_available():
    """R-2-066: the hold already reserved the money, so a capture within the
    remainder must succeed even when the payer's available is zero."""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=500)
    auth_obj = open_authorization(tokens[0], handles[1], amount=500)
    aid = auth_obj["authorization_id"]
    payer = api_get("/me", headers=auth(tokens[0])).json()
    assert payer["available"] == 0
    r = api_post(f"/authorizations/{aid}/capture", json={}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert r.status_code == 201, r.text


# ---------------------------------------------------------------------------
# POST /authorizations/{id}/void — R-2-070..075
# ---------------------------------------------------------------------------

def test_void_requires_payer_no_key():
    """R-2-070"""
    fixture, ids, handles, tokens = n_user_fixture(3)
    auth_obj = open_authorization(tokens[0], handles[1], amount=200)
    aid = auth_obj["authorization_id"]

    not_payer = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[1]))
    assert_error(not_payer, 403, "forbidden")

    third_party = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[2]))
    assert_error(third_party, 403, "forbidden")

    r = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert r.status_code == 200, r.text


def test_void_response_and_release():
    """R-2-071"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=400)
    aid = auth_obj["authorization_id"]
    before = api_get("/me", headers=auth(tokens[0])).json()
    assert before["available"] == 600

    r = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "voided"
    assert body["remaining_amount"] == 0
    assert body["closed_at"] is not None

    after = api_get("/me", headers=auth(tokens[0])).json()
    assert after["total"] == 1000
    assert after["held"] == 0
    assert after["available"] == 1000


def test_void_already_voided_is_200_idempotent():
    """R-2-072"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=200)
    aid = auth_obj["authorization_id"]
    r1 = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert r1.status_code == 200
    r2 = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert r2.status_code == 200
    assert r2.json()["status"] == "voided"


def test_void_captured_or_expired_is_409_not_open():
    """R-2-073"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    auth_obj = open_authorization(tokens[0], handles[1], amount=200)
    aid = auth_obj["authorization_id"]
    captured = api_post(f"/authorizations/{aid}/capture", json={}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert captured.status_code == 201
    void_after_capture = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert_error(void_after_capture, 409, "authorization_not_open")


def test_void_moves_no_money():
    """R-2-075"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=400)
    aid = auth_obj["authorization_id"]
    api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    payer = api_get("/me", headers=auth(tokens[0])).json()
    receiver = api_get("/me", headers=auth(tokens[1])).json()
    assert payer["total"] == 1000
    assert receiver["total"] == 1000


def test_void_on_partial_capture_releases_only_remainder_preserves_captures():
    """R-2-062: void can close a partially captured authorization, releasing
    only the remainder and preserving every capture record."""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    cap = api_post(f"/authorizations/{aid}/capture", json={"amount": 300, "final": False},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text

    before_payer = api_get("/me", headers=auth(tokens[0])).json()
    assert before_payer["total"] == 700 and before_payer["held"] == 700 and before_payer["available"] == 0

    void = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
    assert void.status_code == 200, void.text
    assert void.json()["captured_amount"] == 300
    assert void.json()["payment_ids"] == [cap.json()["payment_id"]]
    assert void.json()["remaining_amount"] == 0
    assert void.json()["status"] == "voided"

    after_payer = api_get("/me", headers=auth(tokens[0])).json()
    assert after_payer["total"] == 700
    assert after_payer["held"] == 0
    assert after_payer["available"] == 700


def test_unknown_authorization_404_for_capture_and_void():
    """R-2-074"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    cap = api_post("/authorizations/totally-unknown/capture", json={},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(cap, 404, "not_found")
    void = api_post("/authorizations/totally-unknown/void", json={}, headers=auth(tokens[0]))
    assert_error(void, 404, "not_found")


# ---------------------------------------------------------------------------
# GET /authorizations — R-2-080..084
# ---------------------------------------------------------------------------

def test_list_visible_only_to_participants_newest_first():
    """R-2-080"""
    fixture, ids, handles, tokens = n_user_fixture(3)
    created_ids = []
    for i in range(3):
        a = open_authorization(tokens[0], handles[1], amount=10 + i, note=f"n{i}")
        created_ids.append(a["authorization_id"])

    third_view = api_get("/authorizations", headers=auth(tokens[2])).json()["authorizations"]
    assert all(a["authorization_id"] not in created_ids for a in third_view)

    owner_view = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    returned_ids = [a["authorization_id"] for a in owner_view if a["authorization_id"] in created_ids]
    assert returned_ids == list(reversed(created_ids))


def test_direction_filter():
    """R-2-081"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    out = open_authorization(tokens[0], handles[1], amount=10)
    inc = open_authorization(tokens[1], handles[0], amount=20)

    outgoing = api_get("/authorizations", headers=auth(tokens[0]), params={"direction": "outgoing"}).json()["authorizations"]
    assert any(a["authorization_id"] == out["authorization_id"] for a in outgoing)
    assert all(a["authorization_id"] != inc["authorization_id"] for a in outgoing)

    incoming = api_get("/authorizations", headers=auth(tokens[0]), params={"direction": "incoming"}).json()["authorizations"]
    assert any(a["authorization_id"] == inc["authorization_id"] for a in incoming)
    assert all(a["authorization_id"] != out["authorization_id"] for a in incoming)

    bad = api_get("/authorizations", headers=auth(tokens[0]), params={"direction": "sideways"})
    assert_error(bad, 422, "validation_failed")


def test_status_filter():
    """R-2-082"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    a = open_authorization(tokens[0], handles[1], amount=10)
    api_post(f"/authorizations/{a['authorization_id']}/void", json={}, headers=auth(tokens[0]))

    voided = api_get("/authorizations", headers=auth(tokens[0]), params={"status": "voided"}).json()["authorizations"]
    assert all(x["status"] == "voided" for x in voided)
    assert any(x["authorization_id"] == a["authorization_id"] for x in voided)

    bad = api_get("/authorizations", headers=auth(tokens[0]), params={"status": "bogus"})
    assert_error(bad, 422, "validation_failed")


def test_pagination_limit_offset_has_more():
    """R-2-083"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    for i in range(5):
        open_authorization(tokens[0], handles[1], amount=1 + i)

    page = api_get("/authorizations", headers=auth(tokens[0]), params={"limit": 2, "offset": 0}).json()
    assert len(page["authorizations"]) == 2
    assert page["has_more"] is True

    past_end = api_get("/authorizations", headers=auth(tokens[0]), params={"limit": 2, "offset": 1000}).json()
    assert past_end["authorizations"] == []
    assert past_end["has_more"] is False

    bad_limit = api_get("/authorizations", headers=auth(tokens[0]), params={"limit": 0})
    assert_error(bad_limit, 422, "validation_failed")
    bad_offset = api_get("/authorizations", headers=auth(tokens[0]), params={"offset": -1})
    assert_error(bad_offset, 422, "validation_failed")


def test_api_json_when_no_html_accept():
    """R-2-084"""
    fixture, ids, handles, tokens = n_user_fixture(2)
    r = api_get("/authorizations", headers={**auth(tokens[0]), "Accept": "application/json"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("application/json")
