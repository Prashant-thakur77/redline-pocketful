"""Adversarial findings against N2-4 (authorizations through export/import:
R-2-170..175, carried R-1-203/204/206/207/208/209).

`validate_import_document` (stage-2/service/snapshot.py) copies each
imported authorization verbatim (`{a["id"]: dict(a) for a in
state.get("authorizations") or []}`) with NO per-field validation —
unlike `fixtures.validate_fixture`, which validates `amount` via
`parse_amount`, validates `captured_amount` is an int between 0 and
`amount`, and requires `expires_at`. Two distinct breaches of R-1-204
follow, confirmed against commit b79a74b:

1. A malformed authorization field that `check_holds_within_balance`
   cannot tolerate (a non-numeric `amount`, a missing `expires_at`)
   raises an uncaught TypeError/KeyError, because that call sits AFTER
   the try/except in `validate_import_document` that catches every
   other per-field parsing error — producing `500 internal_error`
   instead of `422 validation_failed` (R-1-005/R-1-204).
2. A malformed field `check_holds_within_balance` tolerates numerically
   (`captured_amount` > `amount`, or a negative `amount`) is accepted
   outright (`204`) with no validation at all, corrupting the holds
   model: `held` goes negative and `available` exceeds `total` for the
   affected user — the exact "money created from nothing" failure mode
   R-2-005 and R-2-002 exist to prevent, reached via import instead of
   a capture/void race.

The happy-path round trip (expiry across the boundary, partial-capture
state, idempotency identity) was also attacked and holds; those are
included here as regression coverage alongside the breaches."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, authorization,  # noqa: E402
                      idem, login_token, make_fixture, open_authorization, reset_ok, unique,
                      unique_handle, user)


def _export_doc_with_one_hold(amount=500, balance=1000):
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ia"), unique_handle("ib")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=balance, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=amount)],
    ))
    a_token = login_token(f"{a_handle}@example.com")
    doc = api_get("/_test/export").json()
    return doc, a_token, a_id, b_id


def test_import_malformed_authorization_amount_is_422_not_500():
    """BREACH: a string `amount` on an imported authorization crashes
    `check_holds_within_balance` (str - int) with an uncaught TypeError,
    which the pipeline's last-resort handler turns into `500
    internal_error` — R-1-005 forbids this, and R-1-204 requires `422
    validation_failed` for a malformed field, exactly as the reset path
    (`fixtures.validate_fixture`, via `parse_amount`) already does."""
    doc, a_token, a_id, b_id = _export_doc_with_one_hold()
    bad_auths = [dict(a) for a in doc["state"]["authorizations"]]
    bad_auths[0]["amount"] = "not-a-number"
    bad_doc = {**doc, "state": {**doc["state"], "authorizations": bad_auths}}

    r = api_post("/_test/import", json=bad_doc)
    assert r.status_code != 500, f"a malformed amount must never reach the last-resort handler: {r.status_code} {r.text}"
    assert_error(r, 422, "validation_failed")


def test_import_missing_authorization_expires_at_is_422_not_500():
    """BREACH, same root cause: a missing `expires_at` key crashes
    `is_open`'s `authorization["expires_at"] <= now` comparison with an
    uncaught KeyError -> 500, instead of 422 (reset already requires
    expires_at and rejects its absence with 422)."""
    doc, a_token, a_id, b_id = _export_doc_with_one_hold()
    bad_auths = [dict(a) for a in doc["state"]["authorizations"]]
    del bad_auths[0]["expires_at"]
    bad_doc = {**doc, "state": {**doc["state"], "authorizations": bad_auths}}

    r = api_post("/_test/import", json=bad_doc)
    assert r.status_code != 500, f"a missing expires_at must never reach the last-resort handler: {r.status_code} {r.text}"
    assert_error(r, 422, "validation_failed")


def test_import_captured_amount_exceeding_amount_is_rejected():
    """BREACH: an authorization whose `captured_amount` exceeds its
    `amount` is accepted verbatim (204) because the import path never
    runs the bounds check `fixtures.validate_fixture` applies
    (`0 <= captured_amount <= amount`). The result corrupts the holds
    model: `remaining_amount` goes negative, so `held` goes negative and
    `available` exceeds `total` — money the ledger does not have."""
    doc, a_token, a_id, b_id = _export_doc_with_one_hold(amount=500, balance=1000)
    bad_auths = [dict(a) for a in doc["state"]["authorizations"]]
    bad_auths[0]["captured_amount"] = bad_auths[0]["amount"] + 100  # 600 captured of 500
    bad_doc = {**doc, "state": {**doc["state"], "authorizations": bad_auths}}

    r = api_post("/_test/import", json=bad_doc)
    if r.status_code == 204:
        me = api_get("/me", headers=auth(a_token)).json()
        assert me["available"] <= me["total"], (
            f"R-2-002/R-1-207 breach: captured_amount > amount survived import unvalidated, "
            f"producing available ({me['available']}) > total ({me['total']}): {me}"
        )
    assert_error(r, 422, "validation_failed")


def test_import_negative_authorization_amount_is_rejected():
    """BREACH, same class: a negative `amount` is accepted verbatim,
    producing a negative `held` and `available` > `total` for the payer
    — money created from nothing via import rather than a capture/void
    race."""
    doc, a_token, a_id, b_id = _export_doc_with_one_hold(amount=500, balance=1000)
    bad_auths = [dict(a) for a in doc["state"]["authorizations"]]
    bad_auths[0]["amount"] = -500
    bad_doc = {**doc, "state": {**doc["state"], "authorizations": bad_auths}}

    r = api_post("/_test/import", json=bad_doc)
    if r.status_code == 204:
        me = api_get("/me", headers=auth(a_token)).json()
        assert me["available"] <= me["total"], (
            f"R-2-002/R-1-207 breach: negative amount survived import unvalidated, "
            f"producing available ({me['available']}) > total ({me['total']}): {me}"
        )
    assert_error(r, 422, "validation_failed")


def test_expiry_across_import_boundary_releases_with_no_write():
    """Holds (not a breach): a hold seeded to expire in ~2s, re-imported
    verbatim, must read as expired once the deadline passes — released
    into `available` purely by the clock, no write required (R-2-030)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ea"), unique_handle("eb")
    import datetime
    expires_at = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=2)).isoformat()
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=500, expires_at=expires_at)],
    ))
    doc = api_get("/_test/export").json()
    r = api_post("/_test/import", json=doc)
    assert r.status_code == 204, r.text

    time.sleep(2.5)
    a_token = login_token(f"{a_handle}@example.com")
    me = api_get("/me", headers=auth(a_token)).json()
    assert me["available"] == 1000 and me["held"] == 0, me
    feed = api_get("/authorizations", headers=auth(a_token)).json()
    assert feed["authorizations"][0]["status"] == "expired"


def test_partial_capture_state_round_trips_and_remains_capturable():
    """Holds (not a breach): capture 700 of a 2000 hold with final=false,
    export, import; captured_amount/remaining_amount/status/payment_ids
    must survive exactly, and a further capture of the true remainder
    (1300) must still close it and move money exactly once (R-2-033,
    R-2-175, R-2-005)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("pa"), unique_handle("pb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=2000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=2000)],
    ))
    a_token = login_token(f"{a_handle}@example.com")
    b_token = login_token(f"{b_handle}@example.com")
    auth_id = api_get("/authorizations", headers=auth(a_token)).json()["authorizations"][0]["authorization_id"]

    r = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 700, "final": False},
                 headers=auth_idem(b_token, unique("partial")))
    assert r.status_code == 201, r.text

    doc = api_get("/_test/export").json()
    r = api_post("/_test/import", json=doc)
    assert r.status_code == 204, r.text

    a_token = login_token(f"{a_handle}@example.com")
    b_token = login_token(f"{b_handle}@example.com")
    a0 = api_get("/authorizations", headers=auth(a_token)).json()["authorizations"][0]
    assert a0["captured_amount"] == 700
    assert a0["remaining_amount"] == 1300
    assert a0["status"] == "open"
    assert len(a0["payment_ids"]) == 1
    assert a0["closed_at"] is None

    r2 = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 1300},
                  headers=auth_idem(b_token, unique("remainder")))
    assert r2.status_code == 201, r2.text
    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 0 and me["available"] == 0 and me["held"] == 0, me


def test_idempotency_key_identity_survives_import_exactly_once():
    """Holds (not a breach): a completed payment's idempotency record
    survives import (R-1-206); replaying the same key+body returns the
    byte-identical original response and moves no additional money."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ka"), unique_handle("kb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
    ))
    a_token = login_token(f"{a_handle}@example.com")
    key = unique("payk")
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 300}, headers=auth_idem(a_token, key))
    assert r1.status_code == 201, r1.text

    doc = api_get("/_test/export").json()
    r = api_post("/_test/import", json=doc)
    assert r.status_code == 204, r.text

    a_token = login_token(f"{a_handle}@example.com")
    r2 = api_post("/payments", json={"to_handle": b_handle, "amount": 300}, headers=auth_idem(a_token, key))
    assert r2.status_code == 200, r2.text
    assert r2.text == r1.text, "replay after import must return the byte-identical original body (R-1-206)"

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 700 and me["available"] == 700, f"money must move exactly once across the import: {me}"
