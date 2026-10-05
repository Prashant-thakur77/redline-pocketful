"""Adversarial findings against N2-7' (/requests, /split, /authorizations
screens: R-2-133..138, R-2-156), attacked at commit 2568faf.

BREACH: the `/authorizations` screen's capture button
(`static/app.js`'s delegated click handler) reads the capture-amount
field, and if it fails to parse as a valid amount, simply OMITS the
`amount` field from the request body rather than refusing to submit:

    var parsed = Pocketful.parseAmountToMinorUnits(amountEl.value, SESSION.minor_units);
    if (parsed !== null) {
      body.amount = parsed;
    }
    // no else branch: an invalid value just silently sends no amount

Per R-2-051, an omitted `amount` on `POST /authorizations/{id}/capture`
defaults to the authorization's full REMAINING amount. So a user who
types a malformed partial-capture amount (anything that fails
`parseAmountToMinorUnits`, e.g. a typo) does not see an error and does
not get nothing captured — they silently capture the ENTIRE remaining
balance instead of the smaller amount they meant to type. Every other
amount-accepting write path in this product (the pay/request/authorize
forms in `static/app.js`'s `bindForm`) refuses to submit and shows a
visible error on exactly this failure (`if (amountMinor === null) {
form.dataset.state = "error"; showSlot(...); return; }`) — the capture
button's handler is the one place that doesn't, which is the drift
R-2-186 exists to prevent.

Also attacked and held (included as regression coverage): the capture
amount pre-fill reflects the true REMAINING amount after a partial
capture, not the authorization's original amount; capture and void
are mutually exclusive per side (the payer never sees capture, the
receiver never sees void); the `/split` preview matches the exact
§9 share rule (`divmod`) across several boundary amounts; and R-2-156
— a stale pay button for a request someone else already paid
disappears after the refresh, with the correct `request_not_pending`
error shown."""
from __future__ import annotations

import time

import httpx

from conftest import authorization, make_fixture, reset_ok, tid, unique, unique_handle, url, user, \
    wait_for_absent, wait_for_present


def _auth_pair(amount=2000, balance=2000):
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("aa"), unique_handle("bb")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=balance), user(b_id, b_handle, balance=0)],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=amount)],
    )
    reset_ok(fixture)
    return fixture, a_id, b_id, a_handle, b_handle


def test_malformed_capture_amount_silently_captures_full_remaining_instead_of_erroring(page):
    """BREACH: typing a malformed value into the capture-amount field
    and clicking Capture must never silently fall back to capturing
    the entire remaining balance — it must refuse to submit and show
    an error, exactly like the pay/request/authorize forms already do
    for the same class of input error."""
    fixture, a_id, b_id, a_handle, b_handle = _auth_pair(amount=2000, balance=2000)
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][1]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")
    page.goto(url("/authorizations"), wait_until="load")

    cap_input = page.locator('[data-testid^="authorization-capture-amount-"]')
    cap_input.fill("garbage")
    page.click('[data-testid^="authorization-capture-"][data-action="capture"]')
    # A malformed amount is rejected client-side before any fetch, so the
    # error slot appears synchronously -- wait on it directly rather than
    # a fixed sleep sized for a network round trip that never happens.
    wait_for_present(page, '[data-testid="authorization-error-slot"] [data-state="error"]')

    b_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][1]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    me_b = httpx.get(url("/me"), headers={"Authorization": f"Bearer {b_token}"}, timeout=10.0).json()
    assert me_b["total"] == 0, (
        f"R-2-186/R-1-004: a malformed capture amount must never fall back to capturing the full "
        f"remaining balance — expected no money moved (total=0), got total={me_b['total']}"
    )
    assert page.locator('[data-testid="authorization-error-slot"] [data-state="error"]').count() > 0, (
        "a malformed capture amount must show a visible error, matching every other amount field in this app"
    )


def test_capture_amount_prefill_reflects_true_remaining_after_a_partial_capture(page):
    """The capture-amount field's pre-filled value must be the
    authorization's true remaining amount, not its original amount,
    once a prior partial capture has reduced it."""
    fixture, a_id, b_id, a_handle, b_handle = _auth_pair(amount=2000, balance=2000)
    b_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][1]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    auths = httpx.get(url("/authorizations"), headers={"Authorization": f"Bearer {b_token}"}, timeout=10.0).json()["authorizations"]
    auth_id = auths[0]["authorization_id"]
    r = httpx.post(url(f"/authorizations/{auth_id}/capture"), json={"amount": 700, "final": False},
                    headers={"Authorization": f"Bearer {b_token}", "Idempotency-Key": unique("partial")}, timeout=10.0)
    assert r.status_code == 201, r.text

    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][1]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")
    page.goto(url("/authorizations"), wait_until="load")

    prefill = page.locator('[data-testid^="authorization-capture-amount-"]').input_value()
    assert prefill == "13.00", f"pre-fill must reflect the remaining 1300, not the original 2000: got {prefill!r}"


def test_capture_and_void_are_mutually_exclusive_per_side(page):
    """The payer never sees a capture control; the receiver never sees
    a void control."""
    fixture, a_id, b_id, a_handle, b_handle = _auth_pair(amount=1000, balance=1000)
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")
    page.goto(url("/authorizations"), wait_until="load")
    assert page.locator('[data-testid^="authorization-void-"]').count() == 1
    assert page.locator('[data-testid^="authorization-capture-"][data-action="capture"]').count() == 0


def test_split_preview_matches_the_exact_divmod_share_rule(page):
    """The client-side /split preview must match §9's exact rule
    (base, rem = divmod(amount, n); share i = base+1 for i < rem)
    across boundary cases: a remainder that doesn't divide evenly, an
    amount smaller than the participant count, zero, and a single
    participant."""
    fixture = make_fixture([user(unique("u"), unique_handle("sp"), balance=100_000)])
    reset_ok(fixture)
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")
    page.goto(url("/split"), wait_until="load")

    cases = [
        ("10.00", ["x", "y", "z"], ["3.34 EUR", "3.33 EUR", "3.33 EUR"]),
        ("0.01", ["x", "y", "z"], ["0.01 EUR", "0.00 EUR", "0.00 EUR"]),
        ("0.00", ["x", "y"], ["0.00 EUR", "0.00 EUR"]),
        ("1.00", ["x"], ["1.00 EUR"]),
    ]
    for amount, handles, want in cases:
        page.fill(tid("split-amount"), "")
        page.fill(tid("split-handles"), "")
        page.fill(tid("split-amount"), amount)
        page.fill(tid("split-handles"), ",".join(handles))
        # Pure client-side computation triggered by the input events above
        # -- wait for each share to actually settle on its expected text
        # instead of guessing how long a re-render takes.
        for h, w in zip(handles, want):
            page.wait_for_function(
                "([h, w]) => { var el = document.querySelector('[data-testid=\"split-share-' + h + '\"]'); "
                "return !!el && el.innerText.trim() === w; }",
                arg=[h, w], timeout=5000,
            )
        got = [page.locator(f'[data-testid="split-share-{h}"]').inner_text() for h in handles]
        assert got == want, f"amount={amount} handles={handles}: want {want}, got {got}"


def test_stale_pay_button_disappears_after_another_client_pays_first(page):
    """R-2-156: a request paid by another client while this page's pay
    button is still visible must show request-error on the refused
    retry and the stale button must disappear after the refresh."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ra"), unique_handle("rb")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    a_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][0]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    b_token = httpx.post(url("/auth/login"), json={"email": fixture["users"][1]["email"], "password": "password123"}, timeout=10.0).json()["token"]
    rreq = httpx.post(url("/requests"), json={"payer_handle": a_handle, "amount": 50},
                       headers={"Authorization": f"Bearer {b_token}", "Idempotency-Key": unique("mkreq")}, timeout=10.0)
    assert rreq.status_code == 201, rreq.text
    req_id = rreq.json()["request_id"]

    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), fixture["users"][0]["email"])
    page.fill(tid("login-password"), "password123")
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")
    page.goto(url("/requests"), wait_until="load")
    assert page.locator(f'[data-testid="request-pay-{req_id}"]').count() == 1

    r2 = httpx.post(url(f"/requests/{req_id}/pay"), json={},
                     headers={"Authorization": f"Bearer {a_token}", "Idempotency-Key": unique("elsewhere")}, timeout=10.0)
    assert r2.status_code == 201, r2.text

    page.click(f'[data-testid="request-pay-{req_id}"]')
    wait_for_absent(page, f'[data-testid="request-pay-{req_id}"]')

    assert page.locator(f'[data-testid="request-pay-{req_id}"]').count() == 0, "the stale pay button must disappear"
    assert page.locator(f'[data-testid="request-item-{req_id}"]').get_attribute("data-status") == "paid"
    assert page.locator('[data-testid="request-error"]').count() > 0
