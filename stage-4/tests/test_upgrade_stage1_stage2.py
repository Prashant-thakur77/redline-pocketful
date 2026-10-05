"""Bitemporal data survives export/import, and a pre-stage-3-shaped export
document upgrades cleanly: R-3-100..103.

The gate-5 upgrade mechanics (populate/snapshot/carry against a running
old-stage binary) live in invariants/hook.py; this file covers the same
ground at the pytest level, directly against one running stage-3 service,
for what gate 5 cannot isolate on its own: that a payment's full revision
history round-trips through /_test/export + /_test/import, and that an
export document with no "revisions" key at all for a payment (exactly what
a stage-1/2 export looked like, and what `/_test/import` must therefore
still accept) still ends up with a revision 1 once imported. This is the
same revision-1-always-exists trap as test_revisions.py, applied at the
import boundary instead of the creation boundary: a lazy "only synthesize
revision 1 on first correction" implementation would pass every
test_revisions.py case (fresh payments, created on this service) while
failing here, where the payment arrives pre-made via import and is never
corrected at all.
"""
from __future__ import annotations

import copy

from conftest import api_get, api_post, auth, idem, login_token, make_fixture, reset_ok, unique, unique_handle, user


def test_export_import_preserves_revision_history():
    """R-3-100: a payment's corrections, applied before export, must still
    be visible (same revision numbers, amounts, reasons) after an
    import — the revision history is part of the state, not derived
    fresh from the payment's current fields."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=5000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])

    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]
    corr = api_post(f"/payments/{pay_id}/corrections",
                    json={"expected_revision": 1, "amount": 250,
                          "effective_at": "2026-01-01T00:00:00+00:00", "reason": "pre-export-correction"},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text

    before_revisions = api_get(f"/payments/{pay_id}/revisions", headers=auth(token_a)).json()

    document = api_get("/_test/export").json()
    imported = api_post("/_test/import", json=document)
    assert imported.status_code == 204, imported.text

    token_a_after = login_token(fixture["users"][0]["email"])
    after_revisions = api_get(f"/payments/{pay_id}/revisions", headers=auth(token_a_after)).json()
    assert after_revisions == before_revisions


def test_import_document_with_no_revisions_key_still_yields_revision_1():
    """R-3-101, R-3-102: /_test/import must keep accepting a payment with
    no "revisions" key at all (the pre-stage-3 export shape) — and the
    imported payment must still answer a revisions query with a real
    revision 1, not a 404 or an empty history, purely because the source
    document never carried one."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    # b's ending balance must be >= the 300 they're seeded as having
    # received, or the opening instant (R-3-018a) is negative and reset
    # itself 422s — this test is about the no-revisions-key import path,
    # not that check.
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=300)],
        payments=[{"id": "p-no-revisions-1", "from_user_id": a_id, "to_user_id": b_id,
                   "amount": 300, "note": "pre-stage-3 shape", "visibility": "public"}],
    )
    reset_ok(fixture)
    document = copy.deepcopy(api_get("/_test/export").json())
    for p in document["state"].get("payments", []):
        p.pop("revisions", None)
        assert "revisions" not in p

    r = api_post("/_test/import", json=document)
    assert r.status_code == 204, r.text

    token_a = login_token(fixture["users"][0]["email"])
    revisions_resp = api_get("/payments/p-no-revisions-1/revisions", headers=auth(token_a))
    assert revisions_resp.status_code == 200, \
        f"an imported payment with no revisions key must still get a revision 1: {revisions_resp.status_code} {revisions_resp.text}"
    revisions = revisions_resp.json()["revisions"] if isinstance(revisions_resp.json(), dict) else revisions_resp.json()
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert revisions[0]["amount"] == 300
    assert revisions[0]["reason"] == ""
