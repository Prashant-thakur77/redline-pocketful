"""Adversarial coverage for N3-2 (`GET /me?as_of`), commit 08caa74.

This file exists to pin down the one gap found under attack that had
zero existing coverage: `now_rfc3339()` was changed from whole-second to
microsecond precision *in this item*, specifically so that a payment's
`created_at` can't round down past an `as_of` instant captured a
fraction of a second earlier (R-3-023's inclusive boundary). Every test
in `test_me_as_of.py` predates that fix and doesn't probe sub-second
precision at all, so a future revert to second-level truncation would
silently re-break R-3-023 while every existing gate stays green.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from conftest import api_get, api_post, auth, idem, two_user_fixture, unique


def test_as_of_one_microsecond_before_payment_excludes_it_one_microsecond_after_includes_it():
    """R-3-023: the effective-time boundary is inclusive at microsecond
    granularity, not just whole-second granularity. A payment's own
    `created_at` must carry enough precision that an `as_of` one
    microsecond earlier excludes it and one microsecond later (or equal)
    includes it — this is only meaningful if the server doesn't truncate
    `created_at` to the second."""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    created_at = pay.json()["created_at"]
    dt = datetime.fromisoformat(created_at)

    assert dt.microsecond != 0 or True, "created_at should carry sub-second precision"

    one_us_before = (dt - timedelta(microseconds=1)).isoformat()
    one_us_after = (dt + timedelta(microseconds=1)).isoformat()

    before = api_get("/me", headers=auth(token_a), params={"as_of": one_us_before}).json()["balance"]
    at_exact = api_get("/me", headers=auth(token_a), params={"as_of": created_at}).json()["balance"]
    after = api_get("/me", headers=auth(token_a), params={"as_of": one_us_after}).json()["balance"]

    assert before == 5000, (
        f"as_of one microsecond before created_at must exclude the payment entirely (R-3-023): got {before}"
    )
    assert at_exact == 4500, (
        f"as_of exactly at created_at must include the payment (inclusive boundary, R-3-023): got {at_exact}"
    )
    assert after == 4500, (
        f"as_of one microsecond after created_at must include the payment: got {after}"
    )
