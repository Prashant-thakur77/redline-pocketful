"""Payment revision history: R-3-003, R-3-004, R-3-015, R-3-063, R-3-064.

ASSUMED CONTRACT (flagged for @planner/@builder to confirm): GET
/payments/{id}/revisions returns 200 with {"revisions": [...]}, each entry
at least {"revision": int, "amount": int, "effective_at": iso8601,
"reason": str, "recorded_at": iso8601}. Revision 1 is the payment's
ORIGINAL state and always exists, with "reason": "" — it is never lazily
synthesized only once a correction first happens.

The central trap this file exists to catch: revision 1 must exist for
EVERY payment — one created through a normal POST /payments call, one
seeded directly by a fixture, one that is a settlement member, and one
produced by an authorization capture — not only for payments that have
since been corrected. A lazy "materialize revision 1 on first correction"
implementation would pass every test in test_corrections.py (which always
corrects something) while failing every test here.
"""
from __future__ import annotations

from conftest import (api_get, api_post, auth, idem, login_token, make_fixture, n_user_fixture,
                       open_authorization, reset_ok, two_user_fixture, unique, unique_handle, user)


def _revisions(token, payment_id):
    r = api_get(f"/payments/{payment_id}/revisions", headers=auth(token))
    assert r.status_code == 200, f"GET /payments/{payment_id}/revisions failed: {r.status_code} {r.text}"
    body = r.json()
    return body["revisions"] if isinstance(body, dict) else body


def test_revision_1_exists_for_a_plain_direct_payment():
    """R-3-003: a payment nobody has ever corrected must still expose a
    revision 1, not an empty history."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 250},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    revisions = _revisions(token_a, pay_id)
    assert len(revisions) == 1, f"an uncorrected payment must have exactly one revision: {revisions}"
    assert revisions[0]["revision"] == 1
    assert revisions[0]["amount"] == 250
    assert revisions[0]["reason"] == ""


def test_revision_1_exists_for_a_seeded_payment():
    """R-3-003: a payment seeded directly through the fixture (never created
    via POST /payments at all) must still have a revision 1 — the implicit
    original revision is not tied to having gone through the payments API."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    pay_id = unique("p")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)],
        payments=[{"id": pay_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 300,
                   "note": "seed", "visibility": "public"}],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])

    revisions = _revisions(token_a, pay_id)
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert revisions[0]["amount"] == 300
    assert revisions[0]["reason"] == ""


def test_revision_1_exists_for_a_settlement_member_payment():
    """R-3-003: a payment produced as a settlement's member leg must still
    have a revision 1, even though it was never created through the direct
    POST /payments path."""
    a_id, b_id, op_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, op_handle = unique_handle("a"), unique_handle("b"), unique_handle("op")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0), user(op_id, op_handle, balance=0)],
        settlement_operator_ids=[op_id],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_op = login_token(fixture["users"][2]["email"])
    settle = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 40}]},
                      headers={**auth(token_op), **idem(unique("k"))})
    assert settle.status_code == 201, settle.text

    feed = api_get("/activity", headers=auth(token_a)).json()["payments"]
    settlement_payment_id = next(p["payment_id"] for p in feed if p.get("settlement_id"))

    revisions = _revisions(token_a, settlement_payment_id)
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert revisions[0]["amount"] == 40
    assert revisions[0]["reason"] == ""


def test_revision_1_exists_for_a_capture_produced_payment():
    """R-3-003: a payment produced by capturing an authorization must still
    have a revision 1."""
    fixture, token_a, token_b = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    hold = open_authorization(token_a, b_handle, amount=500)
    capture = api_post(f"/authorizations/{hold['authorization_id']}/capture", json={"amount": 300, "final": True},
                       headers={**auth(token_b), **idem(unique("k"))})
    assert capture.status_code == 201, capture.text
    payment_id = capture.json()["payment_ids"][0] if "payment_ids" in capture.json() else capture.json()["payment_id"]

    revisions = _revisions(token_a, payment_id)
    assert len(revisions) == 1
    assert revisions[0]["revision"] == 1
    assert revisions[0]["amount"] == 300
    assert revisions[0]["reason"] == ""


def test_revisions_are_consecutive_and_recorded_at_strictly_increases():
    """R-3-004: a chain of corrections produces revisions 1, 2, 3, ... with
    no gaps, and each one's recorded_at strictly after the last."""
    fixture, token_a, _ = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    for rev, amount in enumerate([200, 300, 150], start=2):
        corr = api_post(f"/payments/{pay_id}/corrections",
                        json={"expected_revision": rev - 1, "amount": amount,
                              "effective_at": "2026-01-01T00:00:00+00:00", "reason": f"step-{rev}"},
                        headers={**auth(token_a), **idem(unique("k"))})
        assert corr.status_code == 201, corr.text

    revisions = sorted(_revisions(token_a, pay_id), key=lambda r: r["revision"])
    assert [r["revision"] for r in revisions] == [1, 2, 3, 4]
    for a, b in zip(revisions, revisions[1:]):
        assert b["recorded_at"] > a["recorded_at"], f"recorded_at did not strictly increase: {revisions}"
    assert revisions[0]["reason"] == ""
    assert [r["reason"] for r in revisions[1:]] == ["step-2", "step-3", "step-4"]


def test_revision_history_visible_to_payer_and_receiver():
    """R-3-015: both parties to a payment can read its revision history, not
    only the payer who corrects it."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    revisions_a = _revisions(token_a, pay_id)
    revisions_b = _revisions(token_b, pay_id)
    assert revisions_a == revisions_b


def test_revision_history_not_visible_to_unrelated_user_even_if_public():
    """R-3-064, per planner's confirmed ruling: only the two parties to a
    payment may read its revision history; a third party gets 404, not
    403 — even when the payment itself is public."""
    fixture3, ids3, handles3, tokens3 = n_user_fixture(3)
    pay = api_post("/payments", json={"to_handle": handles3[1], "amount": 50, "visibility": "public"},
                   headers={**auth(tokens3[0]), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]
    r = api_get(f"/payments/{pay_id}/revisions", headers=auth(tokens3[2]))
    assert r.status_code == 404, r.text


def test_revision_history_requires_auth():
    """R-3-064: no bearer token at all is 401, distinct from the
    non-party 404 above."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 50},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]
    r = api_get(f"/payments/{pay_id}/revisions")
    assert r.status_code == 401, r.text
