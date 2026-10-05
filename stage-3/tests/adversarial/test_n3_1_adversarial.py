"""Adversarial findings against N3-1 (payment revision history / seeded
opening balances), attacked at commit 3f480dc.

BREACH: `validate_payment_history_nonnegative` in `service/revisions.py`
computes the opening balance with `compute_opening_balances(...)` and then
only checks for negativity *after* replaying each payment forward:

    running = compute_opening_balances(wallets, payments)
    for p in ordered_by_time_then_id(payments):
        running[from] -= amount
        running[to] += amount
        if running[from] < 0 or running[to] < 0:
            raise validation_failed(...)

It never checks `running` immediately after computing the opening balance,
before the loop starts. So a fixture where a seeded payment's *receiver*
has a low/zero ending balance can imply a deeply negative balance for that
receiver at the opening instant (before any payment), and reset still
accepts it with 204 — the negative point simply gets masked once the
single payment is replayed forward and the ending balance comes out
nonnegative again.

This violates R-3-018 ("a fixture whose seeded payments imply a negative
balance at any point is `422 validation_failed` from reset") and, via the
`opening_balances` it silently stores (R-3-016), it plants a value that
will violate R-3-002 ("no balance is negative in any historical view...
not at any past effective-time") the moment `GET /me?as_of=<before the
earliest payment>` is built.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_post, unique, unique_handle, user


def test_reset_rejects_a_fixture_whose_opening_balance_is_negative():
    """R-3-018: a receiver whose ending balance is low but who was
    seeded as having received a payment larger than that ending balance
    must be rejected at reset — their balance *before* the payment
    (the opening balance) would have been negative, which is never a
    valid historical state."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("oa"), unique_handle("ob")
    pay_id = unique("pay")
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

    fixture = {
        "currency": "EUR",
        "minor_units": 2,
        "users": [
            user(a_id, a_handle, balance=1000),
            user(b_id, b_handle, balance=0),
        ],
        "payments": [
            {"id": pay_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 1000, "created_at": past},
        ],
    }

    r = api_post("/_test/reset", json=fixture)
    assert r.status_code == 422, (
        f"R-3-018: a seeded payment implying a negative opening balance for the receiver "
        f"(ending balance 0, received 1000 -> opening -1000) must be 422 validation_failed, "
        f"got {r.status_code}: {r.text}"
    )
