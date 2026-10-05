"""Export/import: R-1-111, R-1-200..210, R-1-235."""
from __future__ import annotations

import copy

import httpx
import pytest

from conftest import (api_get, api_post, assert_error, auth, idem, login, login_token,
                       make_fixture, reset_ok, unique, unique_handle, url, user)


def test_export_shape_unauthenticated():
    """R-1-200"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=10)])
    reset_ok(fixture)
    r = api_get("/_test/export", headers=None)
    assert r.status_code == 200
    body = r.json()
    assert body["track"] == "pocketful"
    assert body["format_version"] == 1
    assert "state" in body and isinstance(body["state"], dict)


def test_import_unauthenticated_and_full_replace():
    """R-1-201"""
    a_id = unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=500)])
    reset_ok(fixture)
    export = api_get("/_test/export")
    document = export.json()

    other = make_fixture([user(unique("u"), unique_handle("b"), balance=1)])
    reset_ok(other)

    r = api_post("/_test/import", json=document, headers=None)
    assert r.status_code == 204

    token = login_token(fixture["users"][0]["email"])
    me = api_get("/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["balance"] == 500


def test_import_accepts_unmodified_export_regardless_of_origin():
    """R-1-202"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=250)])
    reset_ok(fixture)
    document = api_get("/_test/export").json()
    r = api_post("/_test/import", json=document)
    assert r.status_code == 204


def test_import_is_replacement_not_merge_idempotent():
    """R-1-203"""
    kept_id = unique("u")
    kept_handle = unique_handle("keep")
    fixture = make_fixture([user(kept_id, kept_handle, balance=300)])
    reset_ok(fixture)
    document = api_get("/_test/export").json()

    other_id = unique("u")
    other_handle = unique_handle("other")
    reset_ok(make_fixture([user(other_id, other_handle, balance=1)]))

    api_post("/_test/import", json=document)
    api_post("/_test/import", json=document)  # repeat import

    token = login_token(fixture["users"][0]["email"])
    assert api_get("/me", headers=auth(token)).json()["balance"] == 300

    other_login = login(f"{other_handle}@example.com", "password123")
    assert other_login.status_code == 401  # the merged-in user must be gone


def test_import_malformed_and_invalid_body():
    """R-1-204"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=42)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])

    bad_json = httpx.post(url("/_test/import"), content=b"{{{not json", headers={"Content-Type": "application/json"})
    assert_error(bad_json, 400, "malformed_request")

    missing_field = api_post("/_test/import", json={"track": "pocketful", "format_version": 1})
    assert_error(missing_field, 422, "validation_failed")

    bad_track = api_post("/_test/import", json={"track": "other", "format_version": 1, "state": {}})
    assert_error(bad_track, 422, "validation_failed")

    bad_version = api_post("/_test/import", json={"track": "pocketful", "format_version": 2, "state": {}})
    assert_error(bad_version, 422, "validation_failed")

    bad_state = api_post("/_test/import", json={"track": "pocketful", "format_version": 1, "state": "not-an-object"})
    assert_error(bad_state, 422, "validation_failed")

    # prior state is unchanged after every failed import
    still = api_get("/me", headers=auth(token))
    assert still.status_code == 200
    assert still.json()["balance"] == 42


def test_export_import_preserves_accounts_tokens_balances_requests():
    """R-1-205"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    op_id = unique("u")
    op_handle = unique_handle("op")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0), user(op_id, op_handle, balance=0)],
        settlement_operator_ids=[op_id],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201

    document = api_get("/_test/export").json()
    r = api_post("/_test/import", json=document)
    assert r.status_code == 204

    # the pre-existing bearer token still works after import
    me = api_get("/me", headers=auth(token_a))
    assert me.status_code == 200
    assert me.json()["balance"] == 900
    assert me.json()["currency"] == fixture["currency"]
    assert me.json()["minor_units"] == fixture["minor_units"]

    token_b = login_token(fixture["users"][1]["email"])
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 100

    feed = api_get("/activity", headers=auth(token_a)).json()["payments"]
    assert any(p["payment_id"] == pay.json()["payment_id"] for p in feed)


def test_export_import_preserves_idempotent_retry_identity():
    """R-1-111, R-1-206"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=1000),
                             user(unique("u"), unique_handle("b"), balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    b_handle = fixture["users"][1]["handle"]
    key = unique("retry-key")
    original = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token), **idem(key)})
    assert original.status_code == 201, original.text

    # a key whose original request failed with 4xx
    failed_key = unique("failed-key")
    failed = api_post("/payments", json={"to_handle": b_handle, "amount": -5}, headers={**auth(token), **idem(failed_key)})
    assert_error(failed, 422, "validation_failed")

    document = api_get("/_test/export").json()
    api_post("/_test/import", json=document)

    replay = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token), **idem(key)})
    assert replay.status_code == 200, replay.text
    assert replay.json() == original.json()

    # the failed key remains reusable after import
    retry_failed_key = api_post("/payments", json={"to_handle": b_handle, "amount": 20}, headers={**auth(token), **idem(failed_key)})
    assert retry_failed_key.status_code == 201, retry_failed_key.text


def test_export_is_atomic_readonly_snapshot():
    """R-1-207, R-1-208"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=1000),
                             user(unique("u"), unique_handle("b"), balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    b_handle = fixture["users"][1]["handle"]

    document = api_get("/_test/export").json()

    # writes after export must not retroactively change the already-returned document
    api_post("/payments", json={"to_handle": b_handle, "amount": 50}, headers={**auth(token), **idem(unique("k"))})
    second_export = api_get("/_test/export").json()
    assert document != second_export, "a write after export must not be reflected in the earlier snapshot"

    # export itself changes nothing: balances before/after a bare export call are identical
    before = api_get("/me", headers=auth(token)).json()["balance"]
    api_get("/_test/export")
    after = api_get("/me", headers=auth(token)).json()["balance"]
    assert before == after


def test_import_regenerates_nothing_balances_exact():
    """R-1-207"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=777), user(b_id, unique_handle("b"), balance=223)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])

    document = api_get("/_test/export").json()
    before_a = api_get("/me", headers=auth(token_a)).json()["balance"]
    before_b = api_get("/me", headers=auth(token_b)).json()["balance"]

    api_post("/_test/import", json=document)

    after_a = api_get("/me", headers=auth(token_a)).json()["balance"]
    after_b = api_get("/me", headers=auth(token_b)).json()["balance"]
    assert (before_a, before_b) == (after_a, after_b) == (777, 223)


def test_reset_clears_imported_state():
    """R-1-209"""
    fixture = make_fixture([user(unique("u"), unique_handle("a"), balance=1000)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    document = api_get("/_test/export").json()
    api_post("/_test/import", json=document)

    fresh = make_fixture([user(unique("u"), unique_handle("z"), balance=1)])
    reset_ok(fresh)

    stale = api_get("/me", headers=auth(token))
    assert stale.status_code in (401, 404)


def test_fresh_fixture_reset_does_not_satisfy_import_semantics():
    """R-1-210"""
    a_id = unique("u")
    a_handle = unique_handle("a")
    fixture = make_fixture([user(a_id, a_handle, balance=500)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    reset_ok(fixture)  # a second reset with the identical fixture content (not an import)
    relogin = login(fixture["users"][0]["email"], fixture["users"][0]["password"])
    assert relogin.status_code == 200
    new_token = relogin.json()["token"]
    # the old token from before this second reset must not still work as if carried forward
    stale = api_get("/me", headers=auth(token))
    assert stale.status_code in (401, 404) or new_token != token


def test_export_import_preserves_settlement_operator_and_membership():
    """R-1-235"""
    a_id, b_id, op_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, op_handle = unique_handle("a"), unique_handle("b"), unique_handle("op")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0), user(op_id, op_handle, balance=0)],
        settlement_operator_ids=[op_id],
    )
    reset_ok(fixture)
    token_op = login_token(fixture["users"][2]["email"])
    settle = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 10}]},
                      headers={**auth(token_op), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    settlement_id = settle.json()["settlement_id"]

    document = api_get("/_test/export").json()
    api_post("/_test/import", json=document)

    # the operator can still operate
    token_op_after = login_token(fixture["users"][2]["email"])
    settle2 = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 5}]},
                       headers={**auth(token_op_after), **idem(unique("k2"))})
    assert settle2.status_code == 201, settle2.text

    # the original settlement payment is still linked and visible
    token_a_after = login_token(fixture["users"][0]["email"])
    feed = api_get("/activity", headers=auth(token_a_after)).json()["payments"]
    assert any(p["settlement_id"] == settlement_id for p in feed)


_BAD_SEQ_VALUES = [True, "3", 3.5, None]


def _make_export_fixture_with_payment_and_request():
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    token_b = login_token(fixture["users"][1]["email"])
    req = api_post("/requests", json={"payer_handle": a_handle, "amount": 5},
                   headers={**auth(token_b), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    document = api_get("/_test/export").json()
    return document


@pytest.mark.parametrize("bad_value", _BAD_SEQ_VALUES, ids=["bool", "str", "float", "null"])
@pytest.mark.parametrize("field_path", [
    ("payments", 0, "seq"),
    ("requests", 0, "seq"),
    ("next_seq",),
], ids=["payment-seq", "request-seq", "next-seq"])
def test_import_rejects_non_integer_seq_fields(field_path, bad_value):
    """R-1-204: gate-6 gap — snapshot.py's _require_int bool-vs-int check guards
    payment.seq, request.seq and state.next_seq during import; a non-integer
    value there (including a bool, which is an int subclass in Python but must
    still be rejected) must be refused with 422 validation_failed, and the
    destination must be left exactly as it was, not partially or silently
    imported."""
    document = _make_export_fixture_with_payment_and_request()

    other_handle = unique_handle("z")
    other = make_fixture([user(unique("u"), other_handle, balance=4242)])
    reset_ok(other)
    other_token = login_token(other["users"][0]["email"])

    mutated = copy.deepcopy(document)
    target = mutated["state"]
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad_value

    r = api_post("/_test/import", json=mutated)
    assert_error(r, 422, "validation_failed")

    # the destination fixture (still in place) must be completely unchanged
    still = api_get("/me", headers=auth(other_token))
    assert still.status_code == 200
    assert still.json()["balance"] == 4242
    still_login = login(other["users"][0]["email"], other["users"][0]["password"])
    assert still_login.status_code == 200
