"""Adversarial findings against N4-3 (POST /correction-batches, R-4-040..061).
Breach confirmed against commit 571aec7.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import api_get, api_post, auth, idem, make_fixture, reset_ok, user, login_token, unique  # noqa: E402


def test_batch_historical_overdraft_check_misses_cross_item_combination_r_3_002():
    """R-3-002 / R-4-049 stage 4: 'no balance is negative in any historical
    view' and batch error precedence names `historical_overdraft` as the
    batch's last-stage check. `correction_batches.py`'s own docstring
    discloses the gap this proves exploitable: its stage-4 historical
    check re-uses the single-correction primitive PER ITEM, each one
    holding every OTHER item's payment at its CURRENT (pre-batch)
    revision -- never the sibling item's own candidate amount. Two items
    can each individually land exactly on the zero boundary when checked
    against the other's unchanged value, while the combined effect of
    applying both pushes a real historical instant negative.

    Construction: A (opening 150) pays B 100 at T1 and C 40 at T2 (T1 <
    T2); a later payment from D restores A's current total to 210 so the
    batch's combined-CURRENT-funds check (R-4-050, stage 3) also sees
    nothing wrong post-batch. A batch raises P1 (A->B) to 110 and P2
    (A->C) to 50 -- a +10 debit each:
      - P1 alone, historical check holds P2 at its OLD amount (40):
        at T1: 150-110=40 (ok); at T2: 150-110-40=0 (ok, boundary).
      - P2 alone, historical check holds P1 at its OLD amount (100):
        at T2: 150-100-50=0 (ok, boundary).
      - combined (what actually happens once the batch commits):
        at T2: 150-110-50=-10 -- negative, and neither per-item check
        above ever evaluates this combination.
    The batch is accepted with 201, and `GET /me?as_of=<T2>` afterward
    reports `total: -10` -- a plain read returning a negative balance,
    the exact thing R-3-002 forbids outright.
    """
    uid_a, h_a = unique("u"), "oa" + unique("")[:7]
    uid_b, h_b = unique("u"), "ob" + unique("")[:7]
    uid_c, h_c = unique("u"), "oc" + unique("")[:7]
    uid_d, h_d = unique("u"), "od" + unique("")[:7]
    email_a, email_b, email_c, email_d = (f"{h}@x.com" for h in (h_a, h_b, h_c, h_d))

    reset_ok(make_fixture(
        [user(uid_a, h_a, balance=150, email=email_a),
         user(uid_b, h_b, balance=0, email=email_b),
         user(uid_c, h_c, balance=0, email=email_c),
         user(uid_d, h_d, balance=300, email=email_d)],
        settlement_operator_ids=[uid_a],
    ))
    token_a = login_token(email_a)
    token_d = login_token(email_d)

    p1 = api_post("/payments", json={"to_handle": h_b, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))}).json()
    p2 = api_post("/payments", json={"to_handle": h_c, "amount": 40},
                   headers={**auth(token_a), **idem(unique("k"))}).json()
    api_post("/payments", json={"to_handle": h_a, "amount": 200},
             headers={**auth(token_d), **idem(unique("k"))})

    before = api_get("/me", headers=auth(token_a)).json()
    assert before["total"] == 210, f"fixture setup assumption wrong: {before}"

    batch = api_post("/correction-batches", json={"corrections": [
        {"payment_id": p1["payment_id"], "expected_revision": 1, "amount": 110,
         "effective_at": p1["created_at"], "reason": "r1"},
        {"payment_id": p2["payment_id"], "expected_revision": 1, "amount": 50,
         "effective_at": p2["created_at"], "reason": "r2"},
    ]}, headers={**auth(token_a), **idem(unique("k"))})

    assert batch.status_code != 201, (
        f"a batch whose combined effect drives a historical balance negative must be rejected "
        f"(422/409, R-4-049's historical-boundary stage), not accepted: {batch.status_code} {batch.text}"
    )

    # If this assertion above ever starts failing (i.e. the batch is wrongly
    # accepted again), this follow-up pins down the actual observable harm:
    view_at_t2 = api_get("/me", headers=auth(token_a), params={"as_of": p2["created_at"]}).json()
    assert view_at_t2["total"] >= 0, (
        f"R-3-002: no balance may be negative in any historical view, got {view_at_t2}"
    )
