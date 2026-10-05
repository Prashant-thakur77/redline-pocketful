"""Upgrade from a populated stage-1 state: R-2-170..175.

A genuine cross-process stage-1 -> stage-2 upgrade is exercised by gate 5
through `invariants/hook.py`'s `populate`/`snapshot`/`carry` (which run the
real stage-1 image and import its export here). These pytest-level tests
approximate the no-holds case the same way R-2-021 already requires the
service to behave: an import whose `state` carries no authorization data
must default every hold to empty, exactly as an omitted `authorizations`
array does on `POST /_test/reset`. That is the actual contract R-2-170
tests — not literally a different service binary.
"""
from __future__ import annotations

from conftest import (api_get, api_post, assert_error, auth, idem, n_user_fixture,
                       open_authorization, unique)


def test_import_of_a_no_holds_export_yields_available_equals_total():
    """R-2-170"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    export = api_get("/_test/export")
    assert export.status_code == 200, export.text
    document = export.json()
    assert document["track"] == "pocketful"
    assert document["format_version"] == 1

    imported = api_post("/_test/import", json=document)
    assert imported.status_code == 204, imported.text

    for token in tokens:
        me = api_get("/me", headers=auth(token)).json()
        assert me["held"] == 0
        assert me["available"] == me["total"]


def test_token_survives_import():
    """R-2-171"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    pre_upgrade_token = tokens[0]
    document = api_get("/_test/export").json()
    r = api_post("/_test/import", json=document)
    assert r.status_code == 204, r.text
    still_works = api_get("/me", headers=auth(pre_upgrade_token))
    assert still_works.status_code == 200, still_works.text


def test_pending_request_payable_after_import():
    """R-2-172"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    req = api_post("/requests", json={"payer_handle": handles[1], "amount": 100},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    req_id = req.json()["request_id"]

    document = api_get("/_test/export").json()
    r = api_post("/_test/import", json=document)
    assert r.status_code == 204, r.text

    pay = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text


def test_claimed_key_remains_retryable_after_import_moves_money_once():
    """R-2-173, R-2-174: the import happens between browser requests here —
    no request is in flight across the import call itself, which is the
    scope R-2-174 actually requires (migration mid-request is out of scope)."""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    key = unique("retry-across-upgrade")
    body = {"to_handle": handles[1], "amount": 150}
    original = api_post("/payments", json=body, headers={**auth(tokens[0]), **idem(key)})
    assert original.status_code == 201, original.text

    document = api_get("/_test/export").json()
    r = api_post("/_test/import", json=document)
    assert r.status_code == 204, r.text

    before = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    replay = api_post("/payments", json=body, headers={**auth(tokens[0]), **idem(key)})
    assert replay.status_code == 200, replay.text
    assert replay.json() == original.json()
    after = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    assert before == after, "a post-import replay must move no additional money"


def test_export_round_trips_authorization_fields():
    """R-2-175"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=1000)
    aid = auth_obj["authorization_id"]
    cap = api_post(f"/authorizations/{aid}/capture", json={"amount": 300, "final": False},
                   headers={**auth(tokens[1]), **idem(unique("k"))})
    assert cap.status_code == 201, cap.text

    before = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    before_match = next(x for x in before if x["authorization_id"] == aid)

    document = api_get("/_test/export").json()
    r = api_post("/_test/import", json=document)
    assert r.status_code == 204, r.text

    after = api_get("/authorizations", headers=auth(tokens[0])).json()["authorizations"]
    after_match = next(x for x in after if x["authorization_id"] == aid)

    assert after_match["status"] == before_match["status"] == "open"
    assert after_match["captured_amount"] == before_match["captured_amount"] == 300
    assert after_match["payment_ids"] == before_match["payment_ids"]
    assert after_match["remaining_amount"] == before_match["remaining_amount"] == 700
    assert after_match["expires_at"] == before_match["expires_at"]
    assert after_match["closed_at"] == before_match["closed_at"] is None
