"""Browser product — wallet display, pay form, decimal input rules, and the
idempotent-resubmit / uncertain-response behaviours: R-2-100..110,
R-2-126..129, R-2-139, R-2-140, R-2-150..158."""
from __future__ import annotations

import httpx

from conftest import (api_get, auth, make_fixture, reset_ok, tid, two_user_fixture,
                       ui_login, ui_login_demo_user, unique, unique_handle, url, user,
                       wait_for_absent, wait_for_dom_change, wait_for_present, wait_for_response_to)

from demo_fixture import ALICE_SEEDED_HELD


def test_formatted_amount_minor_units_rule(page):
    """R-2-100: exactly minor_units decimal places, a single space, then the
    currency code; no decimal point at all when minor_units is 0."""
    jpy_id, jpy_handle = unique("u"), unique_handle("jpy")
    jpy_fixture = make_fixture([user(jpy_id, jpy_handle, balance=1200)], currency="JPY", minor_units=0)
    reset_ok(jpy_fixture)
    ui_login(page, jpy_fixture["users"][0]["email"], jpy_fixture["users"][0]["password"])
    page.goto(url("/"), wait_until="load")
    assert page.locator(tid("wallet-balance")).inner_text().strip() == "1200 JPY"

    bhd_id, bhd_handle = unique("u"), unique_handle("bhd")
    bhd_fixture = make_fixture([user(bhd_id, bhd_handle, balance=10_500)], currency="BHD", minor_units=3)
    reset_ok(bhd_fixture)
    ui_login(page, bhd_fixture["users"][0]["email"], bhd_fixture["users"][0]["password"])
    page.goto(url("/"), wait_until="load")
    assert page.locator(tid("wallet-balance")).inner_text().strip() == "10.500 BHD"


def test_wallet_testids(page, demo):
    """R-2-126, R-2-127, R-2-128"""
    user = ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    balance_el = page.locator(tid("wallet-balance"))
    assert balance_el.count() > 0
    assert balance_el.inner_text().strip() == "100.00 EUR"
    assert balance_el.get_attribute("data-amount") == "10000"

    available_el = page.locator(tid("wallet-available"))
    assert available_el.count() > 0
    assert available_el.inner_text().strip() == "90.00 EUR"
    assert available_el.get_attribute("data-amount") == str(10_000 - ALICE_SEEDED_HELD)

    held_el = page.locator(tid("wallet-held"))
    assert held_el.count() > 0
    assert held_el.inner_text().strip() == "10.00 EUR"
    assert held_el.get_attribute("data-amount") == str(ALICE_SEEDED_HELD)


def test_wallet_held_absent_when_zero(page):
    """R-2-128"""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    reset_ok(fixture)
    ui_login(page, fixture["users"][0]["email"], fixture["users"][0]["password"])
    page.goto(url("/"), wait_until="load")
    assert page.locator(tid("wallet-held")).count() == 0


def test_pay_form_testids_present(page, demo):
    """R-2-129"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    for field in ("pay-handle", "pay-amount", "pay-note", "pay-visibility", "pay-submit"):
        assert page.locator(tid(field)).count() > 0, f"missing {field}"
    options = page.locator(f'{tid("pay-visibility")} option').all_text_contents()
    values = page.eval_on_selector_all(f'{tid("pay-visibility")} option', "els => els.map(e => e.value)")
    assert set(values) == {"public", "private"}


def test_decimal_input_submits_minor_units(page, demo):
    """R-2-101"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "15")
    page.fill(tid("pay-note"), "decimal-15")
    wait_for_response_to(page, lambda: page.click(tid("pay-submit")))

    token = user["token"]
    feed = api_get("/activity", headers=auth(token)).json()["payments"]
    match = next((p for p in feed if p.get("note") == "decimal-15"), None)
    assert match is not None, "payment not found in feed after submit"
    assert match["amount"] == 1500


def test_decimal_input_rejects_too_many_places_without_sending(page, demo):
    """R-2-102"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    page.goto(url("/"), wait_until="load")
    sent = []
    page.route("**/payments", lambda route: (sent.append(route.request), route.abort()))
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "15.005")
    page.click(tid("pay-submit"))
    page.wait_for_timeout(300)
    assert sent == [], "an amount with more than minor_units decimal places must never be sent"
    assert page.locator(tid("pay-error")).count() > 0


def test_authorize_form_testids_present(page, demo):
    """R-2-139"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    for field in ("authorize-handle", "authorize-amount", "authorize-note",
                  "authorize-visibility", "authorize-submit"):
        assert page.locator(tid(field)).count() > 0, f"missing {field}"


def test_wallet_refresh_does_not_clear_pay_form(page, demo):
    """R-2-140"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "7.00")
    page.fill(tid("pay-note"), "keep-me")
    refresh = page.locator(tid("wallet-refresh"))
    assert refresh.count() > 0
    refresh.click()
    page.wait_for_timeout(300)
    assert page.input_value(tid("pay-handle")) == receiver["handle"]
    assert page.input_value(tid("pay-note")) == "keep-me"


def test_pay_form_keeps_values_after_success(page, demo):
    """R-2-150"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "3.00")
    page.fill(tid("pay-note"), "keep-after-success")
    wait_for_response_to(page, lambda: page.click(tid("pay-submit")))
    assert page.input_value(tid("pay-handle")) == receiver["handle"]
    assert page.input_value(tid("pay-amount")) in ("3.00", "3")
    assert page.input_value(tid("pay-note")) == "keep-after-success"


def test_resubmitting_unchanged_form_sends_no_second_payment(page, demo):
    """R-2-151"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    token = user["token"]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "4.00")
    page.fill(tid("pay-note"), "resubmit-test")
    wait_for_response_to(page, lambda: page.click(tid("pay-submit")))
    before = api_get("/activity", headers=auth(token)).json()["payments"]
    before_count = sum(1 for p in before if p.get("note") == "resubmit-test")

    wait_for_response_to(page, lambda: page.click(tid("pay-submit")))
    assert page.locator(tid("pay-error")).count() == 0
    after = api_get("/activity", headers=auth(token)).json()["payments"]
    after_count = sum(1 for p in after if p.get("note") == "resubmit-test")
    assert after_count == before_count == 1


def test_changing_a_field_creates_a_new_payment(page, demo):
    """R-2-152"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    token = user["token"]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "4.00")
    page.fill(tid("pay-note"), "field-change-test")
    balance_before_first = page.locator(tid("wallet-balance")).inner_text()
    page.click(tid("pay-submit"))
    wait_for_dom_change(page, tid("wallet-balance"), balance_before_first)

    balance_before_second = page.locator(tid("wallet-balance")).inner_text()
    page.fill(tid("pay-amount"), "4.50")
    page.click(tid("pay-submit"))
    wait_for_dom_change(page, tid("wallet-balance"), balance_before_second)
    assert page.locator(tid("pay-error")).count() == 0

    feed = api_get("/activity", headers=auth(token)).json()["payments"]
    matches = [p for p in feed if p.get("note") == "field-change-test"]
    assert len(matches) == 2, f"changing amount must produce a second payment, got {matches}"
    assert {m["amount"] for m in matches} == {400, 450}


def test_action_refreshes_without_manual_reload(page, demo):
    """R-2-153"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    page.goto(url("/"), wait_until="load")
    before_balance = page.locator(tid("wallet-balance")).inner_text()
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "2.00")
    page.click(tid("pay-submit"))
    wait_for_dom_change(page, tid("wallet-balance"), before_balance)
    after_balance = page.locator(tid("wallet-balance")).inner_text()
    assert after_balance != before_balance, "balance must update after a successful action with no manual reload"


def test_refused_payment_shows_error_refreshes_preserves_inputs(page, demo):
    """R-2-155"""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    token = user["token"]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "85.00")  # alice's available is 90.00
    page.fill(tid("pay-note"), "about-to-be-outspent")

    # another client spends down alice's available funds first
    spend = httpx.post(url("/payments"), json={"to_handle": receiver["handle"], "amount": 8800},
                       headers={**auth(token), "Idempotency-Key": "other-client-spend"}, timeout=10)
    assert spend.status_code == 201, spend.text

    page.click(tid("pay-submit"))
    wait_for_present(page, tid("pay-error"))
    assert page.locator(tid("pay-error")).count() > 0
    assert page.input_value(tid("pay-handle")) == receiver["handle"]
    assert page.input_value(tid("pay-note")) == "about-to-be-outspent"


def test_pay_uncertain_on_response_lost_after_commit(page, demo):
    """R-2-157, R-2-158: the response is lost AFTER the server has already
    committed the write — built as a client-side failure (the browser's own
    fetch never sees the response), not a server fault, per the dispatch's
    explicit guidance. The real request is forwarded to the live server so
    it genuinely commits; only the browser's view of the response is lost."""
    user = ui_login_demo_user(page, demo["fixture"])
    receiver = demo["fixture"]["users"][1]
    token = user["token"]
    page.goto(url("/"), wait_until="load")
    page.fill(tid("pay-handle"), receiver["handle"])
    page.fill(tid("pay-amount"), "6.00")
    page.fill(tid("pay-note"), "lost-response")

    committed = {}

    def intercept(route):
        req = route.request
        headers = {k: v for k, v in req.headers.items() if k.lower() not in ("content-length", "host")}
        resp = httpx.post(req.url, content=(req.post_data or ""), headers=headers, timeout=10)
        committed["status"] = resp.status_code
        committed["body"] = resp.json() if resp.status_code < 300 else None
        route.abort("failed")

    page.route("**/payments", intercept)
    page.click(tid("pay-submit"))
    # the route is aborted, so the browser never receives a response --
    # wait_for_response_to would hang forever; wait for the resulting DOM
    # state instead.
    wait_for_present(page, tid("pay-uncertain"))

    assert committed.get("status") == 201, f"the server must have committed: {committed}"
    assert page.locator(tid("pay-error")).count() == 0, "a lost response must never be shown as a confirmed rejection"
    uncertain = page.locator(tid("pay-uncertain"))
    assert uncertain.count() > 0
    assert uncertain.inner_text().strip() != ""

    page.unroute("**/payments")
    before = api_get("/me", headers=auth(token)).json()["balance"]
    page.click(tid("pay-submit"))
    # this retry replays the same idempotency key, so the balance does NOT
    # change -- wait for the uncertain marker to clear instead.
    wait_for_absent(page, tid("pay-uncertain"))
    assert page.locator(tid("pay-uncertain")).count() == 0
    assert page.locator(tid("pay-error")).count() == 0
    after = api_get("/me", headers=auth(token)).json()["balance"]
    assert before == after, "the retry must move no additional money (same key, same body)"
