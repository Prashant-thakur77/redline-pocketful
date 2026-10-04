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


def test_import_rejects_a_negative_wallet_balance_r_1_002():
    """R-1-002: 'No wallet balance is ever negative, not even
    transiently... no observable read... leaves a balance below zero.'
    This is an unconditional invariant with no stated exception for
    import.

    Originally filed as a BREACH (commit 0d1b950): `validate_import_document`
    had no equivalent of `fixtures.validate_fixture`'s R-1-045 check, so a
    hand-crafted import document with a negative wallet was accepted
    (204) and the negative balance became observable via GET /me. Fixed
    (R-1-204a): import now validates every wallet balance the same way
    reset does. This test guards the fix — a negative wallet balance in
    an import document must be 422 validation_failed, and the prior
    state (including the real balance) must survive untouched.
    """
    uid, handle = unique("u"), unique_handle("negimp")
    email = f"{handle}@example.com"
    reset_ok(make_fixture([user(uid, handle, balance=500, email=email)]))
    export = _export()

    doc = copy.deepcopy(export)
    doc["state"]["wallets"][uid] = -999_999

    r = _import(doc)
    assert_error(r, 422, "validation_failed")

    token = login_token(email)
    balance = api_get("/me", headers=auth(token)).json()["balance"]
    assert balance == 500, (
        f"a rejected import must change nothing: expected the real balance 500, got {balance}"
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


def test_r_1_203_importing_the_same_document_twice_does_not_duplicate_anything():
    """R-1-203: import is replacement, not merge — repeating the same
    import restores the same state without duplicating anything. Check
    user/payment/request counts, the balance and a replay all come back
    identical after a second, redundant import."""
    uid_a, h_a = unique("u"), unique_handle("dup_a")
    uid_b, h_b = unique("u"), unique_handle("dup_b")
    email_a, email_b = f"{h_a}@example.com", f"{h_b}@example.com"
    reset_ok(make_fixture([user(uid_a, h_a, balance=1000, email=email_a),
                            user(uid_b, h_b, balance=0, email=email_b)]))
    token_a = login_token(email_a)
    key = unique("duppay")
    r_pay = api_post("/payments", json={"to_handle": h_b, "amount": 50},
                      headers=auth_idem(token_a, key))
    assert r_pay.status_code == 201, r_pay.text

    export = _export()
    state = export["state"]

    _import_ok(export)
    _import_ok(export)  # repeat, redundantly

    r_me = api_get("/me", headers=auth(token_a))
    assert r_me.status_code == 200
    assert r_me.json()["balance"] == 1000 - 50

    doc_again = _export()
    assert len(doc_again["state"]["users"]) == len(state["users"]), "user count must not grow"
    assert len(doc_again["state"]["payments"]) == len(state["payments"]), "payment count must not grow"
    assert len(doc_again["state"]["idempotency"]) == len(state["idempotency"]), "idempotency record count must not grow"

    r_replay = api_post("/payments", json={"to_handle": h_b, "amount": 50},
                         headers=auth_idem(token_a, key))
    assert r_replay.status_code == 200, f"the key must still replay cleanly after two imports: {r_replay.text}"


def test_r_1_209_reset_after_import_clears_everything_the_import_brought():
    """R-1-209: POST /_test/reset clears all state including imported
    state — tokens and idempotency records the import restored must not
    survive a subsequent reset."""
    uid, handle = unique("u"), unique_handle("clrimp")
    email = f"{handle}@example.com"
    reset_ok(make_fixture([user(uid, handle, balance=100, email=email)]))
    token = login_token(email)
    export = _export()

    reset_ok(make_fixture([user(unique("u"), unique_handle("other4"), balance=0,
                                 email=unique_email("other4"))]))
    _import_ok(export)

    r_me_before_reset = api_get("/me", headers=auth(token))
    assert r_me_before_reset.status_code == 200, "token must be live immediately after import"

    reset_ok(make_fixture([user(unique("u"), unique_handle("fresh"), balance=0, email=unique_email("fresh"))]))

    r_me_after_reset = api_get("/me", headers=auth(token))
    assert r_me_after_reset.status_code == 401, (
        f"the imported token must not survive a later reset, got {r_me_after_reset.status_code}"
    )
