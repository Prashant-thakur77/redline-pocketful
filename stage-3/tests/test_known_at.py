"""`known_at` — recorded-time visibility: R-3-070..077.

`known_at` selects, for a given payment, the latest revision RECORDED at or
before `known_at` — it is driven by recorded_at, never effective_at (that is
`as_of`'s job). The trap this file exists to catch: if a payment's very
first revision (its creation) was recorded AFTER `known_at`, the payment
must be excluded entirely, as if it had never been created — this is a
different thing from a revision that happens to set amount to 0, which is a
real revision that DOES exist and DOES show up for a `known_at` taken after
it was recorded. A lazy implementation that clamps/zeroes instead of
excluding would pass every amount-based assertion but fail the
existence-based ones below.

ASSUMED CONTRACT (flagged for @planner/@builder to confirm): GET
/payments/{id}/revisions?known_at=T returns the revisions recorded at or
before T; if even revision 1 postdates T, the endpoint responds 404 (the
payment does not exist yet as of that known_at) rather than 200 with an
empty list.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, two_user_fixture, unique


def _iso(dt):
    return dt.isoformat()


def _revisions_known_at(token, payment_id, known_at):
    return api_get(f"/payments/{payment_id}/revisions", headers=auth(token), params={"known_at": _iso(known_at)})


def test_known_at_before_creation_excludes_the_payment_entirely():
    """R-3-070, R-3-073: known_at strictly before a payment's creation
    (its revision 1's recorded_at) must 404 — the payment is not merely
    empty or zeroed, it does not exist yet from that recorded-time view."""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    before = datetime.now(timezone.utc)
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    r = _revisions_known_at(token_a, pay_id, before)
    assert r.status_code == 404, \
        f"known_at before creation must 404 (payment excluded entirely), got {r.status_code} {r.text}"


def test_known_at_after_creation_shows_revision_1():
    """R-3-071"""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]
    after = datetime.now(timezone.utc) + timedelta(seconds=1)

    r = _revisions_known_at(token_a, pay_id, after)
    assert r.status_code == 200, r.text
    revisions = r.json()["revisions"] if isinstance(r.json(), dict) else r.json()
    assert [rv["revision"] for rv in revisions] == [1]
    assert revisions[0]["amount"] == 100


def test_known_at_between_revisions_shows_only_the_earlier_one():
    """R-3-072, R-3-074: a known_at landing strictly between when revision 1
    and revision 2 were RECORDED must show only revision 1 — regardless of
    what either revision's effective_at says."""
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

    r = _revisions_known_at(token_a, pay_id, between)
    assert r.status_code == 200, r.text
    revisions = r.json()["revisions"] if isinstance(r.json(), dict) else r.json()
    assert [rv["revision"] for rv in revisions] == [1], \
        f"a known_at recorded before revision 2 must not show revision 2: {revisions}"
    assert revisions[0]["amount"] == 100


def test_known_at_a_zero_amount_revision_is_present_not_absent():
    """R-3-075: once a zero-amount correction has been RECORDED, a known_at
    taken after it must show that revision present (amount 0) — this is
    the control case distinguishing exclusion (absent) from a legitimate
    zero value (present, amount 0)."""
    fixture, token_a, _ = two_user_fixture(balance_a=10_000, balance_b=0)
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
    r = _revisions_known_at(token_a, pay_id, after)
    assert r.status_code == 200, r.text
    revisions = r.json()["revisions"] if isinstance(r.json(), dict) else r.json()
    assert [rv["revision"] for rv in revisions] == [1, 2]
    assert revisions[1]["amount"] == 0


def test_known_at_malformed_timestamp_422():
    """R-3-076"""
    fixture, token_a, _ = two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    r = api_get(f"/payments/{pay.json()['payment_id']}/revisions", headers=auth(token_a),
                params={"known_at": "not-a-timestamp"})
    assert r.status_code == 422, r.text


def test_known_at_on_me_excludes_a_not_yet_recorded_payment_from_balance():
    """R-3-077: GET /me?known_at before a payment was recorded must show
    the pre-payment balance, exactly as if it had been excluded, not run
    through at a reduced/zeroed amount."""
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
