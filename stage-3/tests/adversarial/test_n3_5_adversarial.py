"""Adversarial findings against N3-5 (known_at selection on GET /me and
GET /statement, R-3-070..078). Run against commit 938b569.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import api_get, api_post, auth, idem, two_user_fixture, unique  # noqa: E402


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
