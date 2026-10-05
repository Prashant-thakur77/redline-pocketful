"""Adversarial findings against N3-8 (historical holds, R-3-110..120).
Run against commit 6463f25 (as landed; confirmed unchanged through 7b55340).
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, auth, idem, open_authorization,  # noqa: E402
                       two_user_fixture, unique)


def _iso(dt):
    return dt.isoformat()


def test_available_goes_negative_at_a_known_at_view_r_3_002():
    """R-3-002: 'No balance is negative in any historical view ... not at
    any past effective-time or event boundary.' `holds.py`'s `remaining_at`
    (and therefore `held_at`) takes only `as_of_epoch` -- it never takes
    `known_at` at all, so an authorization opened AFTER a given `known_at`
    still contributes to `held` at that view. Combined with a correction
    that lowers a payment's amount (recorded after `known_at`, so the
    historical `total` at `known_at` is HIGHER than the live total), the
    live-sized hold can exceed the historical total and `available` goes
    negative -- a plain GET request returning a negative balance, which
    R-3-002 forbids outright.

    Sequence: pay 100 (total 4900) -> known_at_x captured -> correct that
    payment down to 10 (live total back up to 4990, recorded AFTER
    known_at_x so it does not affect the known_at_x view) -> open a hold
    for 4950 using the now-higher live available -> GET /me?known_at=
    known_at_x: total correctly reports 4900 (pre-correction view), but
    `held` uses the CURRENT hold (4950) because known_at never gates it,
    giving available = 4900 - 4950 = -50.
    """
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]

    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    known_at_x = _iso(datetime.now(timezone.utc))

    corr = api_post(f"/payments/{pay_id}/corrections",
                     json={"expected_revision": 1, "amount": 10,
                           "effective_at": pay.json()["created_at"], "reason": "reduce"},
                     headers={**auth(token_a), **idem(unique("k"))})
    assert corr.status_code == 201, corr.text

    hold = open_authorization(token_a, b_handle, amount=4950)
    assert hold["status"] == "open", hold

    view = api_get("/me", headers=auth(token_a), params={"known_at": known_at_x}).json()
    assert view["total"] == 4900, f"historical total at known_at_x must use only the pre-correction revision: {view}"
    assert view["available"] >= 0, (
        f"GET /me must never report a negative available balance at any known_at view (R-3-002), "
        f"got {view}"
    )
    assert view["available"] == view["total"] - view["held"], (
        f"available must equal total - held from the SAME view (R-3-110): {view}"
    )


def test_held_ignores_known_at_entirely_r_3_113():
    """R-3-113: 'Once an authorization's creation is known, its expiry
    deadline is known too' -- implying the inverse: an authorization whose
    creation is NOT yet known (known_at before its created_at) must not
    contribute to `held` at all. `holds.py`'s `remaining_at`/`held_at`
    take no known_at parameter whatsoever, so a hold opened after a given
    known_at still shows up in that view's `held` -- this is the root
    cause behind the negative-available test above, isolated to its
    simplest form: known_at alone (no as_of), before the hold exists,
    must show held=0 / available=total, not the live hold.
    """
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]

    known_at_before_hold = _iso(datetime.now(timezone.utc))
    hold = open_authorization(token_a, b_handle, amount=1000)
    assert hold["status"] == "open", hold

    view = api_get("/me", headers=auth(token_a), params={"known_at": known_at_before_hold}).json()
    assert view["held"] == 0, (
        f"a hold opened after known_at must not be known yet and must not contribute to held "
        f"(R-3-113): {view}"
    )
    assert view["available"] == view["total"] == 5000, view
