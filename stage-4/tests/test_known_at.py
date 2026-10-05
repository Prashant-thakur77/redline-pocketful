"""`known_at` — recorded-time visibility: R-3-070..078.

CONFIRMED CONTRACT (per @planner, commit 900d36d): `known_at` is supported
on exactly two endpoints — GET /me and GET /statement. It selects, for
each payment, the latest revision RECORDED at or before `known_at`; if a
payment's own first revision postdates `known_at`, that payment is
excluded ENTIRELY from the view (not zeroed — a zero-amount revision is a
real, present revision once recorded, which is the control case below).

GET /payments/{id}/revisions does NOT take `known_at` (or `as_of`) at all
(R-3-078): it is an unrecognized query parameter there, so per R-1-023 it
is silently ignored and the complete revision history always comes back.
A 404 from that endpoint means only an unknown payment or a non-party
caller (R-3-064) — never a temporal exclusion. An earlier version of this
file had that backwards; fixed per planner's ruling.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, two_user_fixture, unique


def _iso(dt):
    return dt.isoformat()


def _revisions(token, payment_id, **params):
    return api_get(f"/payments/{payment_id}/revisions", headers=auth(token), params=params or None)


def test_revisions_endpoint_ignores_known_at_even_before_creation():
    """R-3-078, R-1-023: known_at is an unrecognized parameter on this
    endpoint, so it is ignored outright — even a known_at strictly before
    the payment was created must still return 200 with the complete
    history, never a 404 for a temporal reason."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    before = datetime.now(timezone.utc)
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    without_param = _revisions(token_a, pay_id)
    with_param = _revisions(token_a, pay_id, known_at=_iso(before))
    assert with_param.status_code == 200, \
        f"known_at before creation must NOT 404 on /revisions, it is simply ignored: {with_param.status_code} {with_param.text}"
    assert with_param.json() == without_param.json()


def test_revisions_endpoint_ignores_known_at_between_two_revisions():
    """R-3-078: a known_at landing strictly between revision 1 and
    revision 2's recorded_at must NOT filter revision 2 out — the full
    history (both revisions) comes back regardless."""
    fixture, token_a, _ = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    between = datetime.now(timezone.utc) + timedelta(milliseconds=50)
    corr = api_post(f"/payments/{pay_id}/corrections",
                    json={"expected_revision": 1, "amount": 500,
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "later"},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text

    r = _revisions(token_a, pay_id, known_at=_iso(between))
    assert r.status_code == 200, r.text
    revisions = r.json()["revisions"] if isinstance(r.json(), dict) else r.json()
    assert [rv["revision"] for rv in revisions] == [1, 2], \
        f"known_at must be ignored on /revisions — both revisions must still be present: {revisions}"


def test_revisions_endpoint_malformed_known_at_is_also_just_ignored():
    """R-3-078, R-1-023: since known_at is unrecognized here, even a
    malformed value must not be validated/rejected — it is ignored exactly
    like any other unknown query parameter."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    r = _revisions(token_a, pay_id, known_at="not-a-timestamp")
    assert r.status_code == 200, f"a malformed known_at must be ignored, not rejected, on /revisions: {r.status_code} {r.text}"


def test_known_at_on_me_excludes_a_not_yet_recorded_payment_from_balance():
    """R-3-070, R-3-077: GET /me?known_at before a payment was recorded
    must show the pre-payment balance, exactly as if it had been excluded,
    not run through at a reduced/zeroed amount."""
    fixture, token_a, token_b = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    before = datetime.now(timezone.utc)
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    a_before = api_get("/me", headers=auth(token_a), params={"known_at": _iso(before)}).json()["balance"]
    b_before = api_get("/me", headers=auth(token_b), params={"known_at": _iso(before)}).json()["balance"]
    assert a_before == 5000
    assert b_before == 0

    after = datetime.now(timezone.utc) + timedelta(seconds=1)
    a_after = api_get("/me", headers=auth(token_a), params={"known_at": _iso(after)}).json()["balance"]
    b_after = api_get("/me", headers=auth(token_b), params={"known_at": _iso(after)}).json()["balance"]
    assert a_after == 4500
    assert b_after == 500


def test_known_at_on_statement_excludes_a_not_yet_recorded_entry():
    """R-3-070: the same exclusion trap, via GET /statement's entry list
    instead of GET /me's aggregate balance — a known_at before a payment
    was recorded must show no entry for it at all, not a zero entry."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    before = datetime.now(timezone.utc)
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    before_statement = api_get("/statement", headers=auth(token_a), params={"known_at": _iso(before)})
    assert before_statement.status_code == 200, before_statement.text
    before_ids = [e["payment_id"] for e in before_statement.json()["entries"]]
    assert pay_id not in before_ids, "a known_at before the payment was recorded must not list it at all"

    after = datetime.now(timezone.utc) + timedelta(seconds=1)
    after_statement = api_get("/statement", headers=auth(token_a), params={"known_at": _iso(after)})
    assert after_statement.status_code == 200, after_statement.text
    after_ids = [e["payment_id"] for e in after_statement.json()["entries"]]
    assert pay_id in after_ids


def test_known_at_malformed_timestamp_422_on_me():
    """R-3-076: unlike /revisions, GET /me DOES recognize known_at, so a
    malformed value there must be validated and rejected."""
    fixture, token_a, _ = two_user_fixture()
    r = api_get("/me", headers=auth(token_a), params={"known_at": "not-a-timestamp"})
    assert r.status_code == 422, r.text


def test_zero_amount_revision_is_present_not_absent_once_recorded():
    """R-3-075: once a zero-amount correction has been RECORDED, a
    known_at taken after it must show that payment's balance effect as
    zero (present, contributing nothing) — this is recorded on /me the
    same way a real, non-excluded revision is, distinct from a payment
    that was never recorded by that known_at at all (tested above)."""
    fixture, token_a, token_b = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    zero = api_post(f"/payments/{pay_id}/corrections",
                    json={"expected_revision": 1, "amount": 0,
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "zeroed"},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert zero.status_code == 201, zero.text

    after = datetime.now(timezone.utc) + timedelta(seconds=1)
    b_balance = api_get("/me", headers=auth(token_b), params={"known_at": _iso(after)}).json()["balance"]
    assert b_balance == 0

    statement = api_get("/statement", headers=auth(token_b), params={"known_at": _iso(after)})
    assert statement.status_code == 200, statement.text
    entry = next((e for e in statement.json()["entries"] if e["payment_id"] == pay_id), None)
    assert entry is not None, "a recorded zero-amount revision must still be a present entry, not absent"
    assert entry["amount"] == 0

    # revisions, unfiltered as always, shows both the original and the zero correction
    revisions_resp = _revisions(token_a, pay_id)
    revisions = revisions_resp.json()["revisions"] if isinstance(revisions_resp.json(), dict) else revisions_resp.json()
    assert [rv["revision"] for rv in revisions] == [1, 2]
    assert revisions[1]["amount"] == 0
