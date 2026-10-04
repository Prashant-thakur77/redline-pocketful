"""Idempotency: R-1-062, R-1-066, R-1-072, R-1-100..111."""
from __future__ import annotations

import threading
from collections import Counter

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, two_user_fixture as _two_user_fixture, unique, unique_handle, user)


def test_five_paths_require_idempotency_key():
    """R-1-100, R-1-062"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]

    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers=auth(token_a))
    assert_error(r, 400, "missing_idempotency_key")

    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers=auth(token_a))
    assert_error(r, 400, "missing_idempotency_key")

    req = api_post("/requests", json={"payer_handle": b_handle, "amount": 10},
                   headers={**auth(token_a), **idem(unique("k"))})
    req_id = req.json()["request_id"]
    r = api_post(f"/requests/{req_id}/pay", json={}, headers=auth(token_b))
    assert_error(r, 400, "missing_idempotency_key")

    r = api_post("/splits", json={"amount": 10, "participant_handles": [fixture["users"][0]["handle"]]},
                 headers=auth(token_a))
    assert_error(r, 400, "missing_idempotency_key")


def test_other_endpoints_do_not_require_idempotency_key():
    """R-1-100"""
    fixture, token_a, _ = _two_user_fixture()
    assert api_get("/me", headers=auth(token_a)).status_code == 200
    assert api_get("/requests", headers=auth(token_a)).status_code == 200
    assert api_get("/activity", headers=auth(token_a)).status_code == 200


def test_idempotency_scoped_per_user():
    """R-1-101"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=10_000, balance_b=10_000)
    key = unique("shared-key")
    other_handle = unique_handle("third")
    third = user(unique("u"), other_handle, balance=0)
    fixture2 = make_fixture([*fixture["users"], third])
    reset_ok(fixture2)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])

    r1 = api_post("/payments", json={"to_handle": other_handle, "amount": 5},
                  headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post("/payments", json={"to_handle": other_handle, "amount": 7},
                  headers={**auth(token_b), **idem(key)})
    assert r2.status_code == 201, r2.text
    assert r1.json()["amount"] == 5
    assert r2.json()["amount"] == 7


def test_same_key_different_path_is_independent():
    """R-1-102"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("cross-path")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post("/requests", json={"payer_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    assert r2.status_code == 201, r2.text


def test_first_use_returns_201():
    """R-1-103"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201


def test_replay_returns_200_identical_body():
    """R-1-104"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    body = {"to_handle": b_handle, "amount": 10, "note": "hi"}
    r1 = api_post("/payments", json=body, headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post("/payments", json=body, headers={**auth(token_a), **idem(key)})
    assert r2.status_code == 200, r2.text
    assert r1.json() == r2.json()


def test_same_key_different_body_409():
    """R-1-105"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post("/payments", json={"to_handle": b_handle, "amount": 20}, headers={**auth(token_a), **idem(key)})
    assert_error(r2, 409, "idempotency_key_reuse")
    # and nothing changed from the second attempt
    me = api_get("/me", headers=auth(token_a))
    assert me.json()["balance"] == 10_000 - 10


def test_same_body_different_key_order_and_whitespace_is_same_body():
    """R-1-106"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 1000, "note": "x"},
                  headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    # same numeric value via a different JSON number form must be treated as the same body
    r2 = api_post("/payments", json={"note": "x", "to_handle": b_handle, "amount": 1000.0},
                  headers={**auth(token_a), **idem(key)})
    assert r2.status_code == 200, r2.text


def test_absent_vs_default_present_is_different_body():
    """R-1-106"""
    fixture, token_a, token_b = _two_user_fixture()
    req = api_post("/requests", json={"payer_handle": fixture["users"][1]["handle"], "amount": 10},
                   headers={**auth(token_a), **idem(unique("k"))})
    req_id = req.json()["request_id"]
    key = unique("pay-key")
    r1 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post(f"/requests/{req_id}/pay", json={"visibility": "public"}, headers={**auth(token_b), **idem(key)})
    assert_error(r2, 409, "idempotency_key_reuse")


def test_key_reused_after_422_failure_is_first_use():
    """R-1-107: a key reused after the original request failed with
    422 validation_failed (amount genuinely over R-1-134's 1,000,000,000
    cap) is treated as a first use and may succeed."""
    fixture, token_a, _ = _two_user_fixture(balance_a=5)
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 1_000_000_001}, headers={**auth(token_a), **idem(key)})
    assert_error(r1, 422, "validation_failed")
    r2 = api_post("/payments", json={"to_handle": b_handle, "amount": 5}, headers={**auth(token_a), **idem(key)})
    assert r2.status_code == 201, r2.text


def test_key_reused_after_409_failure_is_first_use():
    """R-1-107: "any 4xx" includes 409, not just 422 — a key reused after the
    original request failed with 409 insufficient_funds (amount: 1,000,000
    is within R-1-134's cap, so the honest failure here is funds, not
    validation) is treated as a first use and may succeed."""
    fixture, token_a, _ = _two_user_fixture(balance_a=5)
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 1_000_000}, headers={**auth(token_a), **idem(key)})
    assert_error(r1, 409, "insufficient_funds")
    r2 = api_post("/payments", json={"to_handle": b_handle, "amount": 5}, headers={**auth(token_a), **idem(key)})
    assert r2.status_code == 201, r2.text


def test_concurrent_identical_requests_exactly_one_takes_effect():
    """R-1-003, R-1-108"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("concurrent-key")
    body = {"to_handle": b_handle, "amount": 25}
    results = []
    lock = threading.Lock()

    def go():
        r = api_post("/payments", json=body, headers={**auth(token_a), **idem(key)})
        with lock:
            results.append(r)

    threads = [threading.Thread(target=go) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = Counter(r.status_code for r in results)
    assert statuses[201] == 1, f"expected exactly one 201, got {dict(statuses)}"
    assert statuses[200] == 9, f"expected the rest to be 200 replays, got {dict(statuses)}"
    bodies = {tuple(sorted(r.json().items())) for r in results}
    assert len(bodies) == 1, "all responses must carry the identical body"

    me = api_get("/me", headers=auth(token_a))
    assert me.json()["balance"] == 10_000 - 25, "money must move exactly once"


def test_replay_after_resource_changed_still_returns_original():
    """R-1-109"""
    fixture, token_a, token_b = _two_user_fixture()
    req = api_post("/requests", json={"payer_handle": fixture["users"][1]["handle"], "amount": 10},
                   headers={**auth(token_a), **idem(unique("k"))})
    req_id = req.json()["request_id"]
    key = unique("pay-key")
    r1 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(key)})
    assert r1.status_code == 201, r1.text
    # replay after the request is now `paid`
    r2 = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(token_b), **idem(key)})
    assert r2.status_code == 200, r2.text
    assert r1.json() == r2.json()


def test_idempotency_resolved_before_field_validation():
    """R-1-110"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    # same key, now with an invalid body: idempotency wins, so this is 409, not 422
    r2 = api_post("/payments", json={"to_handle": b_handle, "amount": "not-a-number"},
                  headers={**auth(token_a), **idem(key)})
    assert_error(r2, 409, "idempotency_key_reuse")


def test_idempotency_key_too_long_422():
    """R-1-072"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    long_key = "k" * 256
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(long_key)})
    assert_error(r, 422, "validation_failed")


def test_idempotency_key_max_length_accepted():
    """R-1-072"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = "k" * 255
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(key)})
    assert r.status_code == 201, r.text


def test_idempotency_key_empty_is_missing():
    """R-1-072, R-1-062"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), "Idempotency-Key": ""})
    assert_error(r, 400, "missing_idempotency_key")


# ---------------------------------------------------------------------------
# N1-T.4: R-1-106 / R-1-112 — body-equality edge cases for idempotency
# ---------------------------------------------------------------------------

def test_body_equality_number_vs_boolean_are_different():
    """R-1-106: 1 and true are different JSON values even though the first
    use's amount happens to be numerically truthy — a type difference makes
    the body different, so the second call is a reuse conflict, not a replay."""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    first = api_post("/payments", json={"to_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(key)})
    assert first.status_code == 201, first.text
    second = api_post("/payments", json={"to_handle": b_handle, "amount": True}, headers={**auth(token_a), **idem(key)})
    assert_error(second, 409, "idempotency_key_reuse")


def test_body_equality_unknown_fields_count_toward_equality():
    """R-1-106: unknown fields are ignored for validation (R-1-022) but they
    ARE part of the body for idempotency equality — adding one changes the
    body even though it changes nothing about what gets validated."""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    first = api_post("/requests", json={"payer_handle": b_handle, "amount": 1},
                     headers={**auth(token_a), **idem(key)})
    assert first.status_code == 201, first.text
    second = api_post("/requests", json={"payer_handle": b_handle, "amount": 1, "zz": 2},
                      headers={**auth(token_a), **idem(key)})
    assert_error(second, 409, "idempotency_key_reuse")


def test_body_equality_array_order_matters():
    """R-1-106: unlike object key order, array element order DOES matter —
    two participant lists in a different order are different bodies.
    (/splits is not routed until N1-7, so this is expected red until then.)"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=0), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    key = unique("k")
    first = api_post("/splits", json={"amount": 10, "participant_handles": [a_handle, b_handle]},
                     headers={**auth(token_a), **idem(key)})
    assert first.status_code == 201, first.text
    second = api_post("/splits", json={"amount": 10, "participant_handles": [b_handle, a_handle]},
                      headers={**auth(token_a), **idem(key)})
    assert_error(second, 409, "idempotency_key_reuse")


def test_replay_returns_stored_body_verbatim():
    """R-1-112: a replay returns the stored response body verbatim, never
    re-rendered from the current resource state."""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    key = unique("k")
    body = {"to_handle": b_handle, "amount": 10, "note": "original note"}
    r1 = api_post("/payments", json=body, headers={**auth(token_a), **idem(key)})
    assert r1.status_code == 201, r1.text
    r2 = api_post("/payments", json=body, headers={**auth(token_a), **idem(key)})
    assert r2.status_code == 200, r2.text
    assert r2.json() == r1.json(), "a replay must return the stored response verbatim"
