"""Adversarial findings against N3-5 (known_at selection on GET /me and
GET /statement, R-3-070..078). Run against commit 938b569.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, auth, idem, login_token, make_fixture, reset_ok,  # noqa: E402
                       two_user_fixture, unique, unique_handle, user)


def _iso(dt):
    return dt.isoformat()


def test_statement_does_not_echo_known_at_r_3_076():
    """R-3-076: 'A supplied known_at is echoed back exactly as given.'
    R-3-070 names both GET /me and GET /statement as the two endpoints
    that accept known_at, so R-3-076's echo rule applies to both. GET /me
    does echo it (routes/me.py sets body['known_at'] = fields['known_at_raw']);
    GET /statement's apply() never adds a 'known_at' key to its response
    body at all -- a caller has no way to confirm which known_at a
    statement was actually computed under.
    """
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text

    known_at_raw = _iso(datetime.now(timezone.utc) + timedelta(seconds=5))
    r = api_get("/statement", headers=auth(token_a), params={"known_at": known_at_raw})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("known_at") == known_at_raw, (
        f"GET /statement must echo the supplied known_at exactly as given (R-3-076), "
        f"got body={body!r}"
    )


def test_correction_effective_at_in_the_future_is_rejected_r_3_053():
    """R-3-053: 'effective_at is an RFC 3339 instant not later than now.'
    No tolerance window is named in the requirement text, and the
    existing suite's own test_me_as_of.py documents this reading
    explicitly ('R-3-053 has no future-tolerance window'). The shipped
    corrections.py nonetheless accepts effective_at up to 10 seconds
    ahead of the server's clock (_CLOCK_SKEW_TOLERANCE_SECONDS = 10),
    so a correction dated a few seconds into the future is wrongly
    accepted with 201 instead of 422.
    """
    fixture, token_a, _ = two_user_fixture(balance_a=10_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    future_effective_at = _iso(datetime.now(timezone.utc) + timedelta(seconds=5))
    corr = api_post(f"/payments/{pay_id}/corrections",
                     json={"expected_revision": 1, "amount": 400,
                           "effective_at": future_effective_at, "reason": "future"},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 422, (
        f"effective_at 5s in the future must be 422 validation_failed (R-3-053, no tolerance "
        f"window stated), got {corr.status_code}: {corr.text}"
    )


def test_three_party_conservation_under_shared_effective_instant_corrections_r_3_001():
    """R-3-001/002: the sum of every wallet's balance must equal the
    seeded total at any (as_of/known_at) view -- a per-user historical
    reconstruction can look individually plausible and still fail to
    sum. Two payments from the same payer to two different payees, both
    corrected to an IDENTICAL effective_at but recorded at different
    times, is a sharper test than a single payment: it forces the
    known_at narrowing and the effective-time ordering to agree across
    two independent revision chains at once, not just one.
    """
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([
        user(a_id, a_handle, balance=5000),
        user(b_id, b_handle, balance=0),
        user(c_id, c_handle, balance=0),
    ])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])
    token_c = login_token(fixture["users"][2]["email"])

    pay1 = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert pay1.status_code == 201, pay1.text
    pay2 = api_post("/payments", json={"to_handle": c_handle, "amount": 200},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert pay2.status_code == 201, pay2.text
    pay1_id, pay2_id = pay1.json()["payment_id"], pay2.json()["payment_id"]

    shared_effective_at = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))
    corr1 = api_post(f"/payments/{pay1_id}/corrections",
                      json={"expected_revision": 1, "amount": 150,
                            "effective_at": shared_effective_at, "reason": "tie1"},
                      headers={**auth(token_a), **idem(unique("k"))})
    assert corr1.status_code == 201, corr1.text
    corr2 = api_post(f"/payments/{pay2_id}/corrections",
                      json={"expected_revision": 1, "amount": 250,
                            "effective_at": shared_effective_at, "reason": "tie2"},
                      headers={**auth(token_a), **idem(unique("k"))})
    assert corr2.status_code == 201, corr2.text

    known_at = _iso(datetime.now(timezone.utc) + timedelta(seconds=1))
    balance_a = api_get("/me", headers=auth(token_a), params={"known_at": known_at}).json()["balance"]
    balance_b = api_get("/me", headers=auth(token_b), params={"known_at": known_at}).json()["balance"]
    balance_c = api_get("/me", headers=auth(token_c), params={"known_at": known_at}).json()["balance"]

    assert balance_a + balance_b + balance_c == 5000, (
        f"wallets must sum to the seeded total at any known_at view (R-3-001): "
        f"a={balance_a} b={balance_b} c={balance_c}, sum={balance_a + balance_b + balance_c}"
    )
    assert balance_b == 150 and balance_c == 250


def test_crossed_as_of_and_known_at_both_directions_r_3_073():
    """R-3-073: known_at selects WHICH revision is in play (by
    recorded_at); as_of then applies the selected set by EFFECTIVE
    time. A correction recorded late but effective early is the case
    where an implementation that conflates the two axes breaks, in
    either direction:

    - known_at before the correction was recorded (so it isn't known
      yet) + as_of after the correction's effective_at must still use
      the ORIGINAL revision, not the not-yet-known one.
    - known_at after the correction was recorded (so it IS known) +
      as_of before the correction's effective_at must still use the
      ORIGINAL revision, because as_of has not reached it yet even
      though it is already known.

    Every instant compared against another is either a fixed offset
    from a seeded, explicit past created_at (minutes apart, so no
    amount of request latency can flip their order), or is captured
    immediately before/after an HTTP call whose own completion is the
    only ordering guarantee it needs (recorded_at is always stamped
    strictly after a pre-request capture and strictly before a
    post-response capture) -- never two independently-measured now()
    values compared at sub-second margins, which is what made the
    previous version of this test flake (3/5, builder-reported).
    """
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    created_at = datetime.now(timezone.utc) - timedelta(hours=2)
    pay_id = unique("p")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=5000), user(b_id, b_handle, balance=0)],
        payments=[{"id": pay_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 100,
                   "note": "", "visibility": "public", "created_at": _iso(created_at)}],
    )
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])

    correction_effective_at = created_at + timedelta(minutes=30)
    known_at_before_correction = _iso(datetime.now(timezone.utc))
    corr = api_post(f"/payments/{pay_id}/corrections",
                     json={"expected_revision": 1, "amount": 500,
                           "effective_at": _iso(correction_effective_at), "reason": "backdated"},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text
    known_at_after_correction = _iso(datetime.now(timezone.utc))

    as_of_after_correction_effective = _iso(correction_effective_at + timedelta(minutes=10))
    r1 = api_get("/me", headers=auth(token_a),
                 params={"known_at": known_at_before_correction,
                         "as_of": as_of_after_correction_effective})
    assert r1.status_code == 200, r1.text
    assert r1.json()["balance"] == 4900, (
        "an unknown-yet correction must not be used just because as_of is past its "
        f"effective_at: {r1.json()}"
    )

    as_of_before_correction_effective = _iso(created_at + timedelta(minutes=10))
    r2 = api_get("/me", headers=auth(token_a),
                 params={"known_at": known_at_after_correction,
                         "as_of": as_of_before_correction_effective})
    assert r2.status_code == 200, r2.text
    assert r2.json()["balance"] == 4900, (
        "a now-known correction must not be used before as_of reaches its own "
        f"effective_at: {r2.json()}"
    )


def test_statement_tie_breaks_identical_effective_at_by_payment_id_r_3_038():
    """R-3-038..041: statement entries are ordered by (effective_at,
    payment id). Two different payments corrected to the exact same
    effective_at must come back in ascending payment-id order,
    deterministically, under a known_at view.
    """
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([
        user(a_id, a_handle, balance=5000),
        user(b_id, b_handle, balance=0),
        user(c_id, c_handle, balance=0),
    ])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])

    pay1 = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert pay1.status_code == 201, pay1.text
    pay2 = api_post("/payments", json={"to_handle": c_handle, "amount": 200},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert pay2.status_code == 201, pay2.text
    pay1_id, pay2_id = pay1.json()["payment_id"], pay2.json()["payment_id"]

    shared_effective_at = _iso(datetime.now(timezone.utc) - timedelta(seconds=1))
    corr1 = api_post(f"/payments/{pay1_id}/corrections",
                      json={"expected_revision": 1, "amount": 150,
                            "effective_at": shared_effective_at, "reason": "tie1"},
                      headers={**auth(token_a), **idem(unique("k"))})
    assert corr1.status_code == 201, corr1.text
    corr2 = api_post(f"/payments/{pay2_id}/corrections",
                      json={"expected_revision": 1, "amount": 250,
                            "effective_at": shared_effective_at, "reason": "tie2"},
                      headers={**auth(token_a), **idem(unique("k"))})
    assert corr2.status_code == 201, corr2.text

    known_at = _iso(datetime.now(timezone.utc) + timedelta(seconds=1))
    r = api_get("/statement", headers=auth(token_a), params={"known_at": known_at})
    assert r.status_code == 200, r.text
    entries = r.json()["entries"]
    ids_in_order = [e["payment_id"] for e in entries if e["payment_id"] in (pay1_id, pay2_id)]
    assert ids_in_order == sorted([pay1_id, pay2_id]), (
        f"two entries sharing effective_at must tie-break by ascending payment id: {ids_in_order}"
    )
