"""Upgrade and carried behaviour: R-4-070..072.

For R-4-070 the "pre-stage-4 export" is built from a REAL export of this
service with only the stage-4-specific keys stripped, rather than a
hand-authored document -- the same technique used in stage 3's own
upgrade test, after an earlier attempt at hand-authoring a legacy
document there turned out fragile and was replaced with exactly this.
"""
from __future__ import annotations

import copy

from conftest import api_get, api_post, auth, idem, login_token, make_fixture, n_user_fixture, \
    open_authorization, reset_ok, unique, unique_handle, user


def test_ten_idempotent_write_paths_all_require_a_key():
    """R-4-071: exactly ten idempotent write paths, each independently
    requiring Idempotency-Key."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    pay = api_post("/payments", json={"to_handle": handles[1], "amount": 100},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    req = api_post("/requests", json={"payer_handle": handles[1], "amount": 10},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    req_id = req.json()["request_id"]

    hold = open_authorization(tokens[0], handles[1], amount=200)

    calls_requiring_a_key = [
        ("POST", "/payments", {"to_handle": handles[1], "amount": 10}, tokens[0]),
        ("POST", "/requests", {"payer_handle": handles[1], "amount": 10}, tokens[0]),
        ("POST", f"/requests/{req_id}/pay", {}, tokens[1]),
        ("POST", "/splits", {"amount": 10, "participant_handles": [handles[0], handles[1]]}, tokens[0]),
        ("POST", "/settlements", {"transfers": [{"from_handle": handles[1], "to_handle": handles[2], "amount": 1}]}, tokens[0]),
        ("POST", "/authorizations", {"to_handle": handles[1], "amount": 10}, tokens[0]),
        ("POST", f"/authorizations/{hold['authorization_id']}/capture", {"amount": 1, "final": False}, tokens[1]),
        ("POST", f"/payments/{pay.json()['payment_id']}/corrections",
         {"expected_revision": 1, "amount": 50, "effective_at": "2026-01-01T00:00:00+00:00", "reason": "x"}, tokens[0]),
        ("POST", f"/payments/{pay.json()['payment_id']}/refunds", {"amount": 10}, tokens[1]),
        ("POST", "/correction-batches", {"corrections": []}, tokens[0]),
    ]
    assert len(calls_requiring_a_key) == 10, "R-4-071 names exactly ten idempotent write paths"
    for method, path, body, token in calls_requiring_a_key:
        r = api_post(path, json=body, headers=auth(token))
        assert r.status_code == 400 and r.json()["error"]["code"] == "missing_idempotency_key", \
            f"{method} {path} must require Idempotency-Key, got {r.status_code} {r.text}"


def test_import_of_pre_stage4_shaped_export_still_works():
    """R-4-070: an export with no stage-4-only keys (revisions-shape
    stripped off each payment, standing in for a stage-1/2/3 export) must
    still import cleanly and leave the service fully usable afterward."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    # b's ending balance must be >= the 100 they're seeded as having
    # received, or the opening instant (R-3-018a) is negative and reset
    # itself 422s -- this test is about the legacy import shape, not that
    # check.
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=100)],
        payments=[{"id": unique("p"), "from_user_id": a_id, "to_user_id": b_id, "amount": 100,
                   "note": "pre-stage-4 shape", "visibility": "public"}],
    )
    reset_ok(fixture)
    document = copy.deepcopy(api_get("/_test/export").json())
    for p in document["state"].get("payments", []):
        p.pop("revisions", None)
        p.pop("refund_of", None)

    r = api_post("/_test/import", json=document)
    assert r.status_code == 204, r.text

    token_a = login_token(fixture["users"][0]["email"])
    me = api_get("/me", headers=auth(token_a))
    assert me.status_code == 200
    # R-1-043: the seeded balance is already the POST-payment ending value,
    # so a's balance after import is just 1000, unchanged.
    assert me.json()["balance"] == 1000

    # the service remains fully usable: a fresh refund/correction against
    # the imported payment should work exactly as if seeded with revisions
    exported_payment_id = document["state"]["payments"][0]["id"]
    corr = api_post(f"/payments/{exported_payment_id}/corrections",
                    json={"expected_revision": 1, "amount": 150,
                          "effective_at": "2026-01-01T00:00:00+00:00", "reason": "post-import"},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text


def test_settlement_membership_corrections_and_snapshots_survive_import():
    """R-4-070: settlement membership, corrections and (R-4-072) a saved
    statement snapshot token all survive an export/import round trip."""
    fixture, ids, handles, tokens = n_user_fixture(3, operator_indexes=[0], balance=10_000)
    settle = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[2], "amount": 300}]},
                      headers={**auth(tokens[0]), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text
    settlement_id = settle.json()["settlement_id"]
    settlement_payment_id = settle.json()["payments"][0]["payment_id"]

    # R-4-047: a settlement member can only be corrected via the batch
    # endpoint (by the operator), never the single-correction endpoint,
    # which requires being the payment's original sender.
    corr = api_post("/correction-batches", json={"corrections": [
        {"payment_id": settlement_payment_id, "expected_revision": 1, "amount": 250,
         "effective_at": "2026-01-01T00:00:00+00:00", "reason": "pre-export"}
    ]}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text

    snapshot_before = api_get("/statement", headers=auth(tokens[1]), params={"limit": 5})
    assert snapshot_before.status_code == 200, snapshot_before.text
    token_value = snapshot_before.json().get("snapshot")

    document = api_get("/_test/export").json()
    reimport = api_post("/_test/import", json=document)
    assert reimport.status_code == 204, reimport.text

    feed = api_get("/activity", headers=auth(tokens[1])).json()["payments"]
    restored = next(p for p in feed if p["payment_id"] == settlement_payment_id)
    assert restored["settlement_id"] == settlement_id

    revisions = api_get(f"/payments/{settlement_payment_id}/revisions", headers=auth(tokens[1])).json()
    revs = revisions["revisions"] if isinstance(revisions, dict) else revisions
    assert any(rv["amount"] == 250 for rv in revs), "the pre-export correction must survive import"

    if token_value:
        snapshot_after = api_get("/statement", headers=auth(tokens[1]), params={"limit": 5, "snapshot": token_value})
        assert snapshot_after.status_code == 200, (
            f"a statement snapshot token taken before export must still resolve after import: "
            f"{snapshot_after.status_code} {snapshot_after.text}")
        assert snapshot_after.json() == snapshot_before.json()
