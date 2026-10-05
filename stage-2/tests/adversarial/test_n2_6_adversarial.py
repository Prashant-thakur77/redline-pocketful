"""Adversarial findings against N2-6' (the `/` screen, forms and client
fetch layer: R-2-126..160), attacked at commit 9803a9c.

BREACH: R-2-155 requires that a refused payment "shows pay-error,
refreshes the balance and feed, and preserves all pay inputs." The
write-form submit handler in `service/ui/static/app.js` only refreshes
on success:

    }).then(function (result) {
      if (result.status >= 200 && result.status < 300) {
        form.dataset.state = "idle";
        clearSlot(cfg.prefix);
        refreshAll();           // <- only called here
      } else {
        form.dataset.state = "error";
        showSlot(cfg.prefix, "error", message);
        // no refreshAll() call at all
      }

A refused payment (e.g. another client having spent the balance first,
exactly R-2-155's own scenario) shows `pay-error` and preserves the
inputs correctly, but the displayed `wallet-balance`/`wallet-available`
stay frozen at their pre-attempt values — stale by exactly the amount
the other client spent. The existing acceptance test for this
requirement (`test_ui_wallet_pay.py::
test_refused_payment_shows_error_refreshes_preserves_inputs`) only
asserts the error is shown and the inputs survive; it never reads back
`wallet-balance` after the refusal, so it passes without exercising the
clause it's named for.

The rest of this item's surface was also attacked and holds (included
below as regression coverage): double-click / rapid overlapping submit
never moves money twice; resubmitting an unchanged form after success
sends no second payment; changing a field before resubmitting creates
a genuinely new payment; and the "latest refresh wins" sequence guard
holds against a REAL out-of-order network response (not just a
simulated unit case) — a deliberately delayed first refresh's response
never overwrites a faster second one that arrived first."""
from __future__ import annotations

import time

import httpx

from conftest import auth, make_fixture, reset_ok, tid, unique, unique_handle, url, user


def _two_user_fixture(balance_a=100_000, balance_b=0):
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("pa"), unique_handle("pb")
    fixture = make_fixture([user(a_id, a_handle, balance=balance_a),
                             user(b_id, b_handle, balance=balance_b)])
    reset_ok(fixture)
    return fixture, a_id, b_id, a_handle, b_handle


def test_refused_payment_actually_refreshes_the_displayed_balance(page):
    """R-2-155, the clause the existing test name promises but never
    checks: after a payment is refused because another client spent
    the balance first, the DISPLAYED wallet-balance/available must
    reflect the drained state, not the pre-attempt snapshot."""
    fixture, a_id, b_id, a_handle, b_handle = _two_user_fixture(balance_a=1000)
    a_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][0]["email"], "password": "password123"}, timeout=10.0).json()["token"]

    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")

    page.fill(tid("pay-handle"), b_handle)
    page.fill(tid("pay-amount"), "9.00")  # 900 minor units, affordable right now

    def drain_then_continue(route):
        httpx.post(url("/payments"), json={"to_handle": b_handle, "amount": 999},
                   headers={**auth(a_token), "Idempotency-Key": unique("drain")}, timeout=10.0)
        route.continue_()

    page.route("**/payments", drain_then_continue)
    page.click(tid("pay-submit"))
    page.wait_for_timeout(1500)

    assert page.locator(tid("pay-error")).count() > 0, "a refused payment must show pay-error"
    assert page.input_value(tid("pay-handle")) == b_handle, "inputs must be preserved on refusal"

    balance_el = page.locator(tid("wallet-balance"))
    displayed = balance_el.get_attribute("data-amount")
    assert displayed == "1", (
        f"R-2-155 requires the balance to refresh on a refused payment: expected '1' "
        f"(1000 - 999 drained by the other client), got {displayed!r} (stale pre-attempt value)"
    )


def test_double_click_rapid_resubmit_never_moves_money_twice(page):
    """Two near-simultaneous submits of the unchanged pay form (no field
    edited between them, so the idempotency key is identical) must move
    money exactly once."""
    fixture, a_id, b_id, a_handle, b_handle = _two_user_fixture(balance_a=100_000)
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")

    page.fill(tid("pay-handle"), b_handle)
    page.fill(tid("pay-amount"), "1.00")
    page.click(tid("pay-submit"))
    page.click(tid("pay-submit"))
    page.wait_for_timeout(1500)

    a_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][0]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    me = httpx.get(url("/me"), headers=auth(a_token), timeout=10.0).json()
    activity = httpx.get(url("/activity"), headers=auth(a_token), timeout=10.0).json()
    payments_to_b = [p for p in activity["payments"] if p.get("to_handle") == b_handle]
    assert me["total"] == 99_900, f"exactly one 100-minor-unit payment expected, balance={me['total']}"
    assert len(payments_to_b) == 1, f"exactly one payment expected, found {len(payments_to_b)}"


def test_resubmit_unchanged_then_change_field_moves_money_correctly(page):
    """Resubmitting an unchanged pay form after success sends no second
    payment (R-2-151); changing a field before the next submit creates
    a genuinely new one (R-2-152) — both checked by actual balance
    movement, not just the absence of a visible error."""
    fixture, a_id, b_id, a_handle, b_handle = _two_user_fixture(balance_a=100_000)
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")

    page.fill(tid("pay-handle"), b_handle)
    page.fill(tid("pay-amount"), "0.50")
    page.click(tid("pay-submit"))
    page.wait_for_timeout(1200)
    page.click(tid("pay-submit"))  # unchanged resubmit
    page.wait_for_timeout(1200)

    a_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][0]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    me = httpx.get(url("/me"), headers=auth(a_token), timeout=10.0).json()
    assert me["total"] == 99_950, f"unchanged resubmit must not move money again: balance={me['total']}"

    page.fill(tid("pay-amount"), "0.51")  # change -> new key, new payment
    page.click(tid("pay-submit"))
    page.wait_for_timeout(1200)
    a_token2 = httpx.post(url("/auth/login"), json={"email": fixture["users"][0]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    me2 = httpx.get(url("/me"), headers=auth(a_token2), timeout=10.0).json()
    assert me2["total"] == 99_899, f"a changed field must create a distinct new payment: balance={me2['total']}"


def test_latest_refresh_wins_against_a_real_out_of_order_network_response(page):
    """R-2-154 proven against an actual delayed/reordered network
    response, not a mocked resolution order: the FIRST refresh's
    response is delayed so it physically arrives after the SECOND
    refresh's response, and the state mutates in between. The final
    displayed balance must reflect the second (later, correct) read,
    never the first (earlier, now-stale) one."""
    fixture, a_id, b_id, a_handle, b_handle = _two_user_fixture(balance_a=100_000)
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")

    state = {"count": 0}

    def delay_first(route):
        state["count"] += 1
        if state["count"] == 1:
            time.sleep(1.5)
        route.continue_()

    page.route("**/me", delay_first)
    page.click(tid("wallet-refresh"))  # seq=1, delayed

    a_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][0]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    httpx.post(url("/payments"), json={"to_handle": b_handle, "amount": 1234},
               headers={**auth(a_token), "Idempotency-Key": unique("mutate")}, timeout=10.0)

    page.click(tid("wallet-refresh"))  # seq=2, fast, arrives and applies first
    page.wait_for_timeout(2500)  # let the delayed seq=1 response arrive last

    final = page.locator(tid("wallet-balance")).get_attribute("data-amount")
    assert final == "98766", f"a stale/earlier refresh response must never overwrite a later one: got {final!r}"
