"""Adversarial findings against N3-3.2 (GET /statement, R-3-092 freeze
semantics). Run against commit 9721028.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import api_get, api_post, auth, idem, two_user_fixture, unique  # noqa: E402


def _statement(token, **params):
    return api_get("/statement", headers=auth(token), params=params or None)


def _statement_ok(token, **params):
    r = _statement(token, **params)
    assert r.status_code == 200, f"GET /statement failed: {r.status_code} {r.text}"
    return r.json()


def test_frozen_snapshot_unaffected_by_a_payment_made_after_it_r_3_082_086_088():
    """R-3-082/086/088: a frozen result keeps paging the same entries and
    balances 'even after later payments or corrections' / 'concurrent
    payments or corrections'."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in (10, 20, 30):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    page1 = _statement_ok(token_a, limit=10)
    token = page1["snapshot"]
    assert len(page1["entries"]) == 3

    # A payment made *after* the snapshot was taken.
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 999},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text

    replay = _statement_ok(token_a, snapshot=token, limit=10)
    assert replay["entries"] == page1["entries"], "a later payment leaked into a frozen snapshot"
    assert replay["opening_balance"] == page1["opening_balance"]
    assert replay["closing_balance"] == page1["closing_balance"]
    assert replay["snapshot"] == token


def test_unknown_token_is_404_before_limit_is_validated_r_3_091():
    """R-3-091: '404 not_found for anyone else (R-3-084) takes precedence
    over any validation of the accompanying limit/offset, so a token is
    never confirmed to exist by a differing error.' An unknown token
    combined with a type-invalid `limit` must still surface 404, not 422 —
    otherwise an attacker could use the error code itself as an oracle for
    whether a guessed token string happens to exist."""
    fixture, token_a, _ = two_user_fixture()
    r = _statement(token_a, snapshot="totally-made-up-token-xyz", limit="not-a-number")
    assert r.status_code == 404, (
        f"expected 404 for an unknown token even with an invalid limit, got {r.status_code}: {r.text}"
    )


def test_foreign_users_snapshot_token_is_404_r_3_084():
    """R-3-084: another user's token is 404 (not leaked as 403 or honored)."""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 50},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    token_a_snapshot = _statement_ok(token_a)["snapshot"]

    r = _statement(token_b, snapshot=token_a_snapshot)
    assert r.status_code == 404, f"expected 404 for another user's snapshot token, got {r.status_code}: {r.text}"


def test_snapshot_token_from_before_reset_is_404_r_3_084():
    """R-3-084: 'a token issued before the last reset' is 404."""
    fixture, token_a, _ = two_user_fixture()
    old_token = _statement_ok(token_a)["snapshot"]

    # Re-seed (new fixture, new reset generation) and log back in.
    fixture2, token_a2, _ = two_user_fixture()
    r = _statement(token_a2, snapshot=old_token)
    assert r.status_code == 404, f"pre-reset token should 404, got {r.status_code}: {r.text}"


def test_snapshot_combined_with_from_is_422_r_3_083():
    fixture, token_a, _ = two_user_fixture()
    token = _statement_ok(token_a)["snapshot"]
    r = _statement(token_a, snapshot=token, **{"from": "2026-01-01T00:00:00+00:00"})
    assert r.status_code == 422, f"snapshot+from should be 422, got {r.status_code}: {r.text}"


def test_snapshot_combined_with_to_is_422_r_3_083():
    fixture, token_a, _ = two_user_fixture()
    token = _statement_ok(token_a)["snapshot"]
    r = _statement(token_a, snapshot=token, to="2026-01-01T00:00:00+00:00")
    assert r.status_code == 422, f"snapshot+to should be 422, got {r.status_code}: {r.text}"


def test_repeated_call_same_token_no_offset_always_returns_first_page_r_3_092():
    """R-3-092's exact wording: 'GET /statement?snapshot=T&limit=L with no
    offset returns the first page of T's frozen result every time it is
    called, however many times it is called' — not an advancing cursor."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 6):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    first = _statement_ok(token_a, limit=2)
    token = first["snapshot"]

    repeat1 = _statement_ok(token_a, snapshot=token, limit=2)
    repeat2 = _statement_ok(token_a, snapshot=token, limit=2)
    repeat3 = _statement_ok(token_a, snapshot=token, limit=2)
    for r in (repeat1, repeat2, repeat3):
        assert [e["payment_id"] for e in r["entries"]] == [e["payment_id"] for e in first["entries"]], (
            "calling the same snapshot token with no offset must always return the same first page"
        )
        assert r["snapshot"] == token


def test_offset_beyond_end_of_frozen_result_is_empty_not_error_r_3_086():
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text

    page = _statement_ok(token_a, limit=5)
    token = page["snapshot"]
    far = _statement(token_a, snapshot=token, offset=10_000, limit=5)
    assert far.status_code == 200, far.text
    body = far.json()
    assert body["entries"] == []
    assert body["has_more"] is False


def test_concurrent_reads_of_same_snapshot_return_identical_data_r_3_132():
    """R-3-132: 'A snapshot read concurrent with corrections returns a
    self-consistent frozen result, never a torn mix.' Fire many concurrent
    reads of the same token while hammering the account with new payments
    at the same time; every read of the frozen token must agree exactly
    with every other."""
    fixture, token_a, _ = two_user_fixture(balance_a=50_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 11):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    frozen = _statement_ok(token_a, limit=50)
    token = frozen["snapshot"]

    results = []
    errors = []
    stop = threading.Event()

    def hammer_payments():
        while not stop.is_set():
            api_post("/payments", json={"to_handle": b_handle, "amount": 1},
                     headers={**auth(token_a), **idem(unique("k"))})

    def read_snapshot():
        r = _statement(token_a, snapshot=token, limit=50)
        if r.status_code != 200:
            errors.append((r.status_code, r.text))
        else:
            results.append(r.json())

    writer = threading.Thread(target=hammer_payments)
    writer.start()
    readers = [threading.Thread(target=read_snapshot) for _ in range(20)]
    for t in readers:
        t.start()
    for t in readers:
        t.join()
    stop.set()
    writer.join()

    assert not errors, f"snapshot reads failed during concurrent writes: {errors}"
    assert len(results) == 20
    for r in results[1:]:
        assert r["entries"] == results[0]["entries"], "torn/inconsistent read of a frozen snapshot under concurrency"
        assert r["opening_balance"] == results[0]["opening_balance"]
        assert r["closing_balance"] == results[0]["closing_balance"]
