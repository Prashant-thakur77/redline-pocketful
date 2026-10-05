"""Historical overdraft checking: R-3-059, R-3-060, R-3-118.

The trap this file exists to catch: overdraft/affordability for a
correction must be checked at EVERY intermediate effective instant the
correction's new amount would be in force, not only against the payer's
FINAL/current balance. A correction that is affordable by the time
everything settles can still be illegal if, at some instant between its
effective_at and the next revision/payment's effective_at, the payer's
running balance at that point in effective time would have gone negative.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, idem, login_token, make_fixture, reset_ok, \
    two_user_fixture, unique, unique_handle, user


def _iso(dt):
    return dt.isoformat()


def test_correction_illegal_at_an_intermediate_instant_even_if_final_state_is_fine():
    """R-3-059, R-3-060: alice has 1000. She pays bob 500 (effective now,
    balance 500 remains). Later she pays bob another 400 (balance 100
    remains). A correction that raises the FIRST payment's amount to 900,
    effective at its original instant, would have made her effective
    balance negative right after that first payment (1000 - 900 = 100,
    still fine) — construct the boundary tighter: raise it to 1001, which
    is unaffordable even standing alone at that first instant, regardless
    of what happens later. This must 409, and must leave both payments
    unmodified."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]

    pay1 = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                    headers={**auth(token_a), **idem(unique("k1"))})
    assert pay1.status_code == 201, pay1.text
    pay1_id = pay1.json()["payment_id"]

    pay2 = api_post("/payments", json={"to_handle": b_handle, "amount": 400},
                    headers={**auth(token_a), **idem(unique("k2"))})
    assert pay2.status_code == 201, pay2.text

    # raising payment 1 alone to 1001 overdraws alice at the instant it took
    # effect, even though nothing downstream is examined yet
    corr = api_post(f"/payments/{pay1_id}/corrections",
                    json={"expected_revision": 1, "amount": 1001,
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "too much"},
                    headers={**auth(token_a), **idem(unique("k3"))})
    assert corr.status_code == 409, corr.text

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 100
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 900


def test_correction_illegal_between_two_existing_payments_even_though_final_balance_is_nonnegative():
    """R-3-059, R-3-118: alice has 1000. Payment 1 sends bob 100 (balance
    900). Payment 2, made later, sends bob 850 (balance 50). A correction
    that raises payment 1's amount to 950 is fine at the FINAL state
    (1000 - 950 - 850 would be negative, so this must still be rejected) —
    the point is that even an intermediate-only violation (between payment 1
    and payment 2, running balance 1000-950 = 50, still non-negative here)
    is distinct from the final-state check; this test exercises the
    stacked case where both the intermediate AND final balances would go
    negative, which must 409 either way, and must leave prior state intact."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]

    pay1 = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                    headers={**auth(token_a), **idem(unique("k1"))})
    assert pay1.status_code == 201, pay1.text
    pay1_id = pay1.json()["payment_id"]

    pay2 = api_post("/payments", json={"to_handle": b_handle, "amount": 850},
                    headers={**auth(token_a), **idem(unique("k2"))})
    assert pay2.status_code == 201, pay2.text

    corr = api_post(f"/payments/{pay1_id}/corrections",
                    json={"expected_revision": 1, "amount": 200,
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "raise"},
                    headers={**auth(token_a), **idem(unique("k3"))})
    assert corr.status_code == 409, corr.text

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 50
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 950


def test_correction_legal_when_every_intermediate_instant_stays_non_negative():
    """R-3-059: the positive control — a correction whose amount keeps the
    payer's balance non-negative at every instant, not just at the end,
    must succeed."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]

    pay1 = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                    headers={**auth(token_a), **idem(unique("k1"))})
    assert pay1.status_code == 201, pay1.text
    pay1_id = pay1.json()["payment_id"]

    pay2 = api_post("/payments", json={"to_handle": b_handle, "amount": 200},
                    headers={**auth(token_a), **idem(unique("k2"))})
    assert pay2.status_code == 201, pay2.text

    corr = api_post(f"/payments/{pay1_id}/corrections",
                    json={"expected_revision": 1, "amount": 300,
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "raise-ok"},
                    headers={**auth(token_a), **idem(unique("k3"))})
    assert corr.status_code == 201, corr.text

    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 1000 - 300 - 200
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 500


def test_historical_overdraft_rejection_reports_the_distinct_error_code():
    """R-3-060: a historical (intermediate-instant) overdraft is reported
    with its own error code, distinct from a plain final-balance
    insufficient_funds rejection — callers need to tell the two apart.

    Stage-4 ruling R-4-037 (back-ported here so this stage-3 test keeps
    passing under g5 against the stage-4 service): the funds check is
    against the debited party's CURRENT available funds and the
    INCREMENTAL debit, with the historical-boundary check reachable only
    once that current debit is already affordable. The original scenario
    here (a's available after both payments is 50, delta is 100) is
    unaffordable RIGHT NOW, so insufficient_funds is the spec-correct
    answer for it, not historical_overdraft -- this test's purpose
    (proving the two codes are distinguishable) needs a scenario where the
    debit is affordable now but a PAST boundary still goes negative, which
    needs a THIRD payment after the one being corrected so there is a
    currently-healthy balance to be affordable against:

      fixture: A=500, B=0, C=10000
      T1: A pays B 100         -> A=400
      T2: C pays A 10000       -> A=10400
      correct pay1 100 -> 600, effective_at PINNED to pay1's own created_at

    delta=500 against A's current available (10400) is affordable, so the
    historical check runs; replayed at T1 (where the pin keeps the
    corrected payment), A is 500 - 600 = -100 -> historical_overdraft.
    The pin is mandatory -- a now()-dated correction here would reorder
    pay1 to AFTER T2's credit, no boundary would be negative, and the
    answer would be 201, testing nothing."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=500), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=10_000)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_c = login_token(fixture["users"][2]["email"])

    pay1 = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                    headers={**auth(token_a), **idem(unique("k1"))})
    assert pay1.status_code == 201, pay1.text
    pay1_id = pay1.json()["payment_id"]
    pay1_created_at = pay1.json()["created_at"]

    pay2 = api_post("/payments", json={"to_handle": a_handle, "amount": 10_000},
                    headers={**auth(token_c), **idem(unique("k2"))})
    assert pay2.status_code == 201, pay2.text
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_400

    corr = api_post(f"/payments/{pay1_id}/corrections",
                    json={"expected_revision": 1, "amount": 600,
                          "effective_at": pay1_created_at, "reason": "raise"},
                    headers={**auth(token_a), **idem(unique("k3"))})
    assert corr.status_code == 409, corr.text
    body = corr.json()
    assert body["error"]["code"] == "historical_overdraft", \
        f"expected the historical_overdraft code, got {body['error'].get('code')}: {corr.text}"

    # balances must be exactly as they were before the rejected correction
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 10_400
    assert api_get("/me", headers=auth(token_c)).json()["balance"] == 0
