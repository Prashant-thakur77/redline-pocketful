"""Adversarial findings against N2-4B's widened import validation
(`validate_import_document`, commit 2c3544f), attacking the opposite
failure mode from the original N2-4 breach: a validator that rejects
a document it must accept (false `422`) is as much a breach as one
that silently accepts garbage (R-1-202/R-2-170). All held — every
check below is regression coverage, not a repro, kept so a future
tightening of the per-field checks can't silently start rejecting
legitimate data.

One cosmetic (non-functional) finding, not filed as a test: a
reset-seeded user dict carries a vestigial `balance` key (the
authoritative copy lives in `wallets`) that `_validate_user` does not
preserve across a re-import, and a never-captured authorization gains
explicit `closed_at: null`/`payment_ids: []` keys on re-import that the
original seeded dict never had. Neither is visible through any real
API response — `GET /me` reads `wallets`, and `serialize_authorization`
already reads both fields via `.get()` with the same defaults either
way — so export-before != export-after is not a functional breach, just
confirmed to have zero observable effect before being set aside."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, auth, auth_idem, authorization,  # noqa: E402
                      login_token, make_fixture, reset_ok, unique, unique_handle, user)


def test_boundary_amount_and_captured_amount_round_trip_clean():
    """amount at exactly 1 and exactly 1_000_000_000, captured_amount at
    exactly 0 and exactly equal to amount, a note at the 500-char max, a
    20-char handle, and a unicode/emoji display_name must all survive an
    unmodified export/re-import at 204, never a false 422."""
    a_id, b_id = unique("u"), unique("u")
    handle20 = "h" * 20
    b_handle = unique_handle("bb")
    note_max = "n" * 500
    reset_ok(make_fixture(
        [user(a_id, handle20, balance=1_000_000_000, email=f"{a_id}@example.com", display_name="José \U0001F600"),
         user(b_id, b_handle, balance=0, email=f"{b_id}@example.com")],
        authorizations=[
            authorization(unique("auth"), a_id, b_id, amount=1_000_000_000, note=note_max, captured_amount=0),
            authorization(unique("auth"), a_id, b_id, amount=1, status="captured", captured_amount=1),
        ],
    ))
    before = api_get("/_test/export").json()
    r = api_post("/_test/import", json=before)
    assert r.status_code == 204, f"an unmodified boundary-value export must re-import clean: {r.status_code} {r.text}"


def test_claimed_max_length_idempotency_key_round_trips_clean():
    """A payment completed under a 255-character Idempotency-Key (the
    exact R-1-072 maximum) must still be present in the export, must
    not cause a false 422 on re-import, and the key must still replay
    correctly to the byte-identical original body afterward (R-1-206)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ka"), unique_handle("kb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_id}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_id}@example.com")],
    ))
    a_token = login_token(f"{a_id}@example.com")
    key255 = "k" * 255
    r1 = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                  headers=auth_idem(a_token, key255))
    assert r1.status_code == 201, r1.text
    first_body = r1.text

    doc = api_get("/_test/export").json()
    r2 = api_post("/_test/import", json=doc)
    assert r2.status_code == 204, f"a claimed 255-char idempotency key must not cause a false reject: {r2.status_code} {r2.text}"

    a_token2 = login_token(f"{a_id}@example.com")
    r3 = api_post("/payments", json={"to_handle": b_handle, "amount": 100}, headers=auth_idem(a_token2, key255))
    assert r3.status_code == 200 and r3.text == first_body, "the 255-char key must still replay the exact original body after import"


def test_empty_and_sparse_collections_round_trip_clean():
    """A state with no payments, no requests, no settlements, no
    authorizations, no claimed idempotency keys, and an empty
    settlement_operator_ids list must re-import at 204."""
    uid_ = unique("u")
    reset_ok(make_fixture([user(uid_, unique_handle("solo"), balance=500, email=f"{uid_}@example.com")]))
    doc = api_get("/_test/export").json()
    r = api_post("/_test/import", json=doc)
    assert r.status_code == 204, f"a minimal/empty-collections export must re-import clean: {r.status_code} {r.text}"


def test_a_real_settlement_and_a_paid_request_round_trip_clean():
    """Structurally valid but less common shapes: a settlement that
    actually moved money, and a request that has already been paid
    (payment_id pointing at a real payment) — both must survive export
    and re-import at 204, with the payment_id reference and the moved
    money intact."""
    op_id, r1_id = unique("u"), unique("u")
    op_handle, r1_handle = unique_handle("op"), unique_handle("r1")
    reset_ok(make_fixture(
        [user(op_id, op_handle, balance=1000, email=f"{op_id}@example.com"),
         user(r1_id, r1_handle, balance=0, email=f"{r1_id}@example.com")],
        settlement_operator_ids=[op_id],
    ))
    op_token = login_token(f"{op_id}@example.com")
    rs = api_post("/settlements", json={"transfers": [{"from_handle": op_handle, "to_handle": r1_handle, "amount": 300}]},
                  headers=auth_idem(op_token, unique("settle")))
    assert rs.status_code == 201, rs.text

    doc = api_get("/_test/export").json()
    r = api_post("/_test/import", json=doc)
    assert r.status_code == 204, f"a real settlement must re-import clean: {r.status_code} {r.text}"

    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("pa"), unique_handle("pb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_id}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_id}@example.com")],
    ))
    a_token = login_token(f"{a_id}@example.com")
    b_token = login_token(f"{b_id}@example.com")
    rreq = api_post("/requests", json={"payer_handle": a_handle, "amount": 100}, headers=auth_idem(b_token, unique("mkreq")))
    assert rreq.status_code == 201, rreq.text
    request_id = rreq.json()["request_id"]
    rpay = api_post(f"/requests/{request_id}/pay", json={}, headers=auth_idem(a_token, unique("pay")))
    assert rpay.status_code == 201, rpay.text

    doc2 = api_get("/_test/export").json()
    req_before = next(x for x in doc2["state"]["requests"] if x["id"] == request_id)
    r2 = api_post("/_test/import", json=doc2)
    assert r2.status_code == 204, f"a paid request must re-import clean: {r2.status_code} {r2.text}"

    a_token2 = login_token(f"{a_id}@example.com")
    doc3 = api_get("/_test/export").json()
    req_after = next(x for x in doc3["state"]["requests"] if x["id"] == request_id)
    assert req_after["payment_id"] == req_before["payment_id"]
    me = api_get("/me", headers=auth(a_token2)).json()
    assert me["total"] == 900, f"money must move exactly once across the round trip: {me}"


def test_double_and_triple_import_of_the_same_document_is_stable():
    """R-1-203: repeating the same import restores the same state
    without duplicating anything, and must never flip from accept to
    reject on a later pass of the identical document.

    Compares against the export taken *after* the first import, not
    the pre-import seed: a reset-seeded record can carry defaulted
    fields (e.g. a never-captured authorization's `closed_at`/
    `payment_ids`) that `_validate_authorization` always makes explicit
    on the way back out, which is a one-time, purely cosmetic
    normalization with no observable API effect — not evidence of
    duplication, which is what this test actually guards against."""
    uid_ = unique("u")
    reset_ok(make_fixture([user(uid_, unique_handle("trip"), balance=500, email=f"{uid_}@example.com")]))
    seed_doc = api_get("/_test/export").json()
    r1 = api_post("/_test/import", json=seed_doc)
    assert r1.status_code == 204, r1.text
    doc = api_get("/_test/export").json()

    r2 = api_post("/_test/import", json=doc)
    r3 = api_post("/_test/import", json=doc)
    assert (r2.status_code, r3.status_code) == (204, 204)
    after = api_get("/_test/export").json()
    assert after == doc, "re-importing an already-normalized document must not change state further"


def test_stage1_export_imports_clean_with_zero_holds():
    """R-2-170: a stage-1 export (no authorizations key at all) must
    import at 204 with available == total for every user; this is the
    end-to-end path, exercised against the live stage-2 service using a
    hand-built stage-1-shaped document (no authorizations/
    authorization_ttl_seconds keys, matching stage-1's actual export
    shape) rather than standing up a second service."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("s1a"), unique_handle("s1b")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_id}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_id}@example.com")],
    ))
    doc = api_get("/_test/export").json()
    stage1_shaped_state = dict(doc["state"])
    del stage1_shaped_state["authorizations"]
    del stage1_shaped_state["authorization_ttl_seconds"]
    stage1_doc = {**doc, "state": stage1_shaped_state}

    r = api_post("/_test/import", json=stage1_doc)
    assert r.status_code == 204, f"a stage-1-shaped export (no authorizations key) must import clean: {r.status_code} {r.text}"

    a_token = login_token(f"{a_id}@example.com")
    me = api_get("/me", headers=auth(a_token)).json()
    assert me["available"] == me["total"] == 1000 and me["held"] == 0, me


def test_malformed_idempotency_section_leaves_everything_else_byte_identical():
    """The atomicity claim: `IDEMPOTENCY.restore()` runs inside
    `apply_import` after every other collection is already swapped in,
    so a crash there used to risk a half-replaced destination. A
    malformed idempotency record with everything else in the document
    valid must be 422, and the destination must be untouched."""
    uid_ = unique("u")
    reset_ok(make_fixture([user(uid_, unique_handle("atom"), balance=500, email=f"{uid_}@example.com")]))
    before = api_get("/_test/export").json()

    bad_state = dict(before["state"])
    bad_state["idempotency"] = [{"user_id": 123, "method": "POST", "path": "/payments", "key": "k",
                                  "request_body": {}, "response_status": 201, "response_body": {}}]
    bad_doc = {**before, "state": bad_state}
    r = api_post("/_test/import", json=bad_doc)
    assert r.status_code == 422, r.text

    after = api_get("/_test/export").json()
    assert before == after, "a rejected import must leave the destination byte-identical (R-1-204)"
