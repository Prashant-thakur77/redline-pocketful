"""Adversarial findings against N4-6 (statement_snapshots export/import
round trip, R-4-070..072). Breach confirmed against commit 40cc5c0.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import BASE_URL, api_get, api_post, auth, idem, make_fixture, reset_ok, user, login_token, unique  # noqa: E402


def _raw_import(doc):
    req = urllib.request.Request(
        BASE_URL + "/_test/import", data=json.dumps(doc).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_import_accepts_statement_snapshot_missing_entries_then_crashes_on_read_r_1_005():
    """R-1-005: no request may produce a 5xx response, including a GET
    far downstream of a crafted import. `snapshot.py`'s
    `validate_import_document` validates a `statement_snapshots` entry's
    `user_id` against the known users but never checks that `entries`
    (a list), `opening_balance` or `closing_balance` (ints) are even
    present -- `statement.py`'s own read path does plain `frozen["entries"]`
    / `frozen["opening_balance"]` / `frozen["closing_balance"]` dict
    access with no `.get()` fallback. An import whose state carries a
    syntactically-valid-looking snapshot record (a real user_id, nothing
    else) is accepted with 204, and the first `GET /statement?snapshot=`
    naming that token crashes with an uncaught `KeyError`, surfaced as a
    bare `500 internal_error` -- never a validation_failed at the import
    door it should have been caught at.
    """
    uid_a, h_a = unique("u"), "sx" + unique("")[:7]
    email_a = f"{h_a}@x.com"
    reset_ok(make_fixture([user(uid_a, h_a, balance=1000, email=email_a)]))
    token_a = login_token(email_a)

    export = api_get("/_test/export", headers=auth(token_a)).json()
    export["state"]["statement_snapshots"]["ZZMALFORMED"] = {"user_id": uid_a}

    status, body = _raw_import(export)
    assert status in (204, 422), f"unexpected import status: {status} {body}"
    if status == 422:
        return  # already fixed to reject the malformed shape at the import door -- good.

    r = api_get("/statement", headers=auth(token_a), params={"snapshot": "ZZMALFORMED"})
    assert r.status_code < 500, (
        f"R-1-005: a malformed imported snapshot record must never crash a later read with a 5xx: "
        f"{r.status_code} {r.text}"
    )
