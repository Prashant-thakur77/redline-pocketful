"""Adversarial findings against N1-9 (GET /_test/export, POST /_test/import)."""
from __future__ import annotations

import copy
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, login_token,  # noqa: E402
                      make_fixture, reset_ok, unique, unique_email, unique_handle, user)


def _export():
    r = api_get("/_test/export")
    assert r.status_code == 200, r.text
    return r.json()


def _import(doc):
    return api_post("/_test/import", json=doc)


def _import_ok(doc):
    r = _import(doc)
    assert r.status_code == 204, f"import failed: {r.status_code} {r.text}"
    return r


def test_import_accepts_a_negative_wallet_balance_r_1_002():
    """R-1-002: 'No wallet balance is ever negative, not even
    transiently... no observable read... leaves a balance below zero.'
    This is an unconditional invariant with no stated exception for
    import.

    `POST /_test/reset` explicitly rejects a negative seeded balance
    (R-1-045, validated in fixtures.py). `POST /_test/import`'s
    `validate_import_document` has no equivalent check —
    `wallets = {uid: int(balance) for uid, balance in
    state["wallets"].items()}` accepts any integer, including negative
    ones, and `Store.apply_import` assigns it directly. Since
    `POST /_test/import` is unauthenticated (R-1-201) and nothing
    requires its body to have come from this service's own
    `GET /_test/export` (R-1-202 only describes the *expected* use, it
    does not say anything else must be *rejected*), a caller can hand
    craft a document with an arbitrary negative wallet and have it
    accepted, then observe that negative balance directly via GET /me.
    """
    uid, handle = unique("u"), unique_handle("negimp")
    email = f"{handle}@example.com"
    reset_ok(make_fixture([user(uid, handle, balance=500, email=email)]))
    export = _export()

    doc = copy.deepcopy(export)
    doc["state"]["wallets"][uid] = -999_999

    r = _import(doc)
    assert r.status_code == 204, (
        f"expected the import to be rejected for a negative wallet balance, but it was "
        f"accepted: {r.status_code} {r.text}"
    )

    token = login_token(email)
    balance = api_get("/me", headers=auth(token)).json()["balance"]
    assert balance >= 0, (
        f"R-1-002 violated: GET /me reports balance={balance} after an import carrying a "
        "negative wallet — import must validate wallet balances the same way reset does "
        "(R-1-045) instead of trusting the document verbatim"
    )


def test_r_1_206_idempotency_replay_survives_export_import_round_trip():
    """R-1-206: export/import preserves every completed idempotent
    request body with its original response, so a retry after import
    returns the original response. Tested as a genuine round trip: pay,
    export, reset to a DIFFERENT state (proving nothing survives by
    accident), import the export back, then replay the original key."""
    uid_a, h_a = unique("u"), unique_handle("imp_a")
    uid_b, h_b = unique("u"), unique_handle("imp_b")
    email_a, email_b = f"{h_a}@example.com", f"{h_b}@example.com"
    reset_ok(make_fixture([user(uid_a, h_a, balance=1000, email=email_a),
                            user(uid_b, h_b, balance=0, email=email_b)]))
    token_a = login_token(email_a)

    key = unique("roundtrip")
    r_pay = api_post("/payments", json={"to_handle": h_b, "amount": 100},
                      headers=auth_idem(token_a, key))
    assert r_pay.status_code == 201, r_pay.text
    original_body = r_pay.json()

    export = _export()

    # Prove nothing survives by accident: wipe to an unrelated fixture.
    reset_ok(make_fixture([user(unique("u"), unique_handle("other"), balance=0,
                                 email=unique_email("other"))]))

    _import_ok(export)

    r_replay = api_post("/payments", json={"to_handle": h_b, "amount": 100},
                         headers=auth_idem(token_a, key))
    assert r_replay.status_code == 200, f"replay after import must be 200: {r_replay.text}"
    assert r_replay.json() == original_body, (
        f"replay body after import must be verbatim: {r_replay.json()} != {original_body}"
    )


def test_r_1_205_every_pre_existing_token_still_authenticates_after_import():
    """R-1-205: export/import preserves every existing bearer token —
    not just the account, the token string itself, so a client holding
    it from before the import doesn't need to re-login."""
    uid, handle = unique("u"), unique_handle("tok")
    email = f"{handle}@example.com"
    reset_ok(make_fixture([user(uid, handle, balance=10, email=email)]))
    token = login_token(email)

    export = _export()
    reset_ok(make_fixture([user(unique("u"), unique_handle("other2"), balance=0,
                                 email=unique_email("other2"))]))
    _import_ok(export)

    r = api_get("/me", headers=auth(token))
    assert r.status_code == 200, f"pre-import token must still authenticate: {r.status_code} {r.text}"
    assert r.json()["user_id"] == uid


def test_r_1_207_balances_after_import_equal_balances_at_export_exactly():
    """R-1-207: import regenerates no monetary record and never replays
    exported payments against an already-net balance. A wallet whose
    balance would differ from the sum of its payments (an impossible
    state to reach through normal API use, but exactly what export
    captures verbatim) must come back unchanged, not recomputed."""
    uid_a, h_a = unique("u"), unique_handle("bal_a")
    uid_b, h_b = unique("u"), unique_handle("bal_b")
    email_a, email_b = f"{h_a}@example.com", f"{h_b}@example.com"
    reset_ok(make_fixture(
        [user(uid_a, h_a, balance=1000, email=email_a), user(uid_b, h_b, balance=500, email=email_b)],
        payments=[{"id": "seed-p1", "from_user_id": uid_a, "to_user_id": uid_b, "amount": 9999,
                   "note": "", "visibility": "public"}],
    ))
    bal_a_before = api_get("/me", headers=auth(login_token(email_a))).json()["balance"]
    bal_b_before = api_get("/me", headers=auth(login_token(email_b))).json()["balance"]

    export = _export()
    reset_ok(make_fixture([user(unique("u"), unique_handle("other3"), balance=0,
                                 email=unique_email("other3"))]))
    _import_ok(export)

    bal_a_after = api_get("/me", headers=auth(login_token(email_a))).json()["balance"]
    bal_b_after = api_get("/me", headers=auth(login_token(email_b))).json()["balance"]
    assert (bal_a_after, bal_b_after) == (bal_a_before, bal_b_before), (
        f"balances must be exactly as exported, not recomputed: "
        f"before=({bal_a_before},{bal_b_before}) after=({bal_a_after},{bal_b_after})"
    )


def test_r_1_204_malformed_import_bodies_change_nothing():
    """R-1-204: a body that doesn't parse is 400; a missing field, wrong
    track, wrong format_version, or invalid state is 422; every failure
    case leaves the destination state unchanged."""
    uid, handle = unique("u"), unique_handle("guard")
    email = f"{handle}@example.com"
    reset_ok(make_fixture([user(uid, handle, balance=777, email=email)]))
    token = login_token(email)

    bad_docs = [
        ({"format_version": 1, "state": {}}, 422, "validation_failed"),  # missing track
        ({"track": "wrong", "format_version": 1, "state": {}}, 422, "validation_failed"),
        ({"track": "pocketful", "format_version": 2, "state": {}}, 422, "validation_failed"),
        ({"track": "pocketful", "format_version": 1, "state": "not an object"}, 422, "validation_failed"),
        ({"track": "pocketful", "format_version": 1, "state": {"currency": "EUR"}}, 422, "validation_failed"),
    ]
    for doc, status, code in bad_docs:
        r = _import(doc)
        assert_error(r, status, code)

    r_malformed = api_post("/_test/import", json=None, content=b"not json at all")
    assert_error(r_malformed, 400, "malformed_request")

    balance = api_get("/me", headers=auth(token)).json()["balance"]
    assert balance == 777, f"a rejected import must change nothing, got balance {balance}"


def test_export_is_atomic_snapshot_under_concurrent_writes():
    """R-1-208: export is an atomic, read-only snapshot. Fire a payment
    concurrently with repeated exports and verify every single export's
    snapshot has internally-consistent wallets (sum unchanged — the
    export can show pre- or post-payment state, but never a half-applied
    one where the sum of wallets in that snapshot differs from the
    seeded total)."""
    uid_a, h_a = unique("u"), unique_handle("exp_a")
    uid_b, h_b = unique("u"), unique_handle("exp_b")
    email_a, email_b = f"{h_a}@example.com", f"{h_b}@example.com"
    total = 10_000
    reset_ok(make_fixture([user(uid_a, h_a, balance=total, email=email_a),
                            user(uid_b, h_b, balance=0, email=email_b)]))
    token_a = login_token(email_a)

    snapshots = []
    stop = threading.Event()

    def exporter():
        while not stop.is_set():
            doc = _export()
            snapshots.append(sum(doc["state"]["wallets"].values()))

    t = threading.Thread(target=exporter)
    t.start()

    for i in range(20):
        r = api_post("/payments", json={"to_handle": h_b, "amount": 10},
                      headers=auth_idem(token_a, unique(f"exportrace{i}")))
        assert r.status_code == 201, r.text

    stop.set()
    t.join(timeout=5.0)

    assert snapshots, "the exporter must have captured at least one snapshot"
    bad = [s for s in snapshots if s != total]
    assert not bad, f"export observed a snapshot whose wallet sum wasn't conserved: {bad}"
