"""Browser product — quality, responsiveness, accessibility, demo data, and
refresh semantics: R-2-103..111, R-2-141, R-2-154, R-2-159, R-2-160."""
from __future__ import annotations

import httpx

from conftest import (api_get, auth, make_fixture, reset_ok, tid, ui_login,
                      ui_login_demo_user, unique, unique_handle, url, user)
from demo_fixture import ALICE_SEEDED_HELD

VIEWPORTS = {375: 812, 768: 1024, 1280: 800}
SMALL_CONTROLS_JS = """() => [...document.querySelectorAll('button,[role=button],input:not([type=hidden]),select,textarea')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24); })
  .map(e => e.outerHTML.slice(0, 80))"""


def test_primary_actions_are_real_buttons_with_text(page, demo):
    """R-2-103: a minimal, structural proxy for "primary actions are easy to
    identify" — each is an actual interactive control with visible text,
    not a bare clickable div."""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    for field in ("pay-submit", "request-submit", "authorize-submit"):
        el = page.locator(tid(field))
        assert el.count() > 0
        tag = el.evaluate("e => e.tagName.toLowerCase()")
        assert tag in ("button",) or el.evaluate("e => e.type") == "submit", f"{field} is a <{tag}>, not a real control"
        assert el.inner_text().strip() != "" or el.get_attribute("value"), f"{field} has no visible label"


def test_available_is_visually_the_headline_number(page, demo):
    """R-2-104"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    available_size = page.locator(tid("wallet-available")).evaluate(
        "e => parseFloat(getComputedStyle(e).fontSize)")
    total_size = page.locator(tid("wallet-balance")).evaluate(
        "e => parseFloat(getComputedStyle(e).fontSize)")
    assert available_size >= total_size, (
        f"available ({available_size}px) must be at least as prominent as total ({total_size}px), "
        "and R-2-104 expects it to be the headline")


def test_available_and_held_are_visually_distinguishable(page, demo):
    """R-2-105"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    available_style = page.locator(tid("wallet-available")).evaluate(
        "e => getComputedStyle(e).color + getComputedStyle(e).fontWeight + getComputedStyle(e).fontSize")
    held_style = page.locator(tid("wallet-held")).evaluate(
        "e => getComputedStyle(e).color + getComputedStyle(e).fontWeight + getComputedStyle(e).fontSize")
    assert available_style != held_style, "available and held must be visually distinct, not just different numbers"


def test_no_horizontal_overflow_at_required_viewports(page, demo):
    """R-2-107"""
    ui_login_demo_user(page, demo["fixture"])
    for width, height in VIEWPORTS.items():
        page.set_viewport_size({"width": width, "height": height})
        for route in ("/", "/requests", "/split", "/authorizations"):
            page.goto(url(route), wait_until="load")
            overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            assert not overflow, f"{route} overflows horizontally at {width}px"


def test_no_undersized_controls_at_375(page, demo):
    """R-2-110"""
    ui_login_demo_user(page, demo["fixture"])
    page.set_viewport_size({"width": 375, "height": 812})
    for route in ("/", "/requests", "/split", "/authorizations"):
        page.goto(url(route), wait_until="load")
        small = page.evaluate(SMALL_CONTROLS_JS)
        assert small == [], f"{route} @375px has undersized control(s): {small}"


def test_every_input_has_a_visible_label(page, demo):
    """R-2-108"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    for field in ("pay-handle", "pay-amount", "pay-note", "request-handle", "request-amount"):
        el = page.locator(tid(field))
        assert el.count() > 0
        name = el.evaluate("""e => {
            const id = e.getAttribute('id');
            const byFor = id ? document.querySelector(`label[for="${id}"]`) : null;
            return (byFor && byFor.innerText.trim()) || e.getAttribute('aria-label') ||
                   (e.closest('label') && e.closest('label').innerText.trim()) || '';
        }""")
        assert name, f"{field} has no associated visible label or aria-label"


def test_empty_requests_and_authorizations_markers(page):
    """R-2-109"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=100), user(b_id, unique_handle("b"), balance=0)])
    reset_ok(fixture)
    ui_login(page, fixture["users"][0]["email"], fixture["users"][0]["password"])
    page.goto(url("/requests"), wait_until="load")
    assert page.locator(tid("empty-requests")).count() > 0
    page.goto(url("/authorizations"), wait_until="load")
    assert page.locator(tid("empty-authorizations")).count() > 0


def test_seeded_demo_user_sees_populated_first_screen(page, demo):
    """R-2-111"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    assert page.locator(tid("wallet-balance")).count() > 0
    assert page.locator(tid("activity-item-p-seed-1")).count() > 0

    page.goto(url("/requests"), wait_until="load")
    assert page.locator(tid("incoming-list")).count() > 0
    assert page.locator(tid("outgoing-list")).count() > 0
    assert page.locator(f'{tid("incoming-list")} [data-testid^="request-item-"]').count() >= 1
    assert page.locator(f'{tid("outgoing-list")} [data-testid^="request-item-"]').count() >= 1


def test_ui_reflects_holds_immediately_after_reset(page, demo):
    """R-2-141"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    held_el = page.locator(tid("wallet-held"))
    assert held_el.count() > 0
    assert held_el.get_attribute("data-amount") == str(ALICE_SEEDED_HELD)
    available_el = page.locator(tid("wallet-available"))
    assert available_el.get_attribute("data-amount") == str(10_000 - ALICE_SEEDED_HELD)


def test_refresh_button_updates_available_and_held(page, demo):
    """R-2-160"""
    user = ui_login_demo_user(page, demo["fixture"])
    bob = demo["fixture"]["users"][1]
    token = demo["tokens"][user["handle"]]["token"]
    page.goto(url("/"), wait_until="load")
    before_available = page.locator(tid("wallet-available")).get_attribute("data-amount")

    new_hold = httpx.post(url("/authorizations"), json={"to_handle": bob["handle"], "amount": 500},
                          headers={**auth(token), "Idempotency-Key": "refresh-held-check"}, timeout=10)
    assert new_hold.status_code == 201, new_hold.text

    page.locator(tid("wallet-refresh")).click()
    page.wait_for_timeout(400)
    after_available = page.locator(tid("wallet-available")).get_attribute("data-amount")
    assert after_available != before_available
    assert int(after_available) == int(before_available) - 500


def test_latest_refresh_wins_even_out_of_order(page, demo):
    """R-2-154: a delayed EARLIER read must never overwrite a LATER refresh.
    Built by controlling response timing from the test: the first /me
    response is delayed so the second one (triggered after a real balance
    change) arrives first."""
    user = ui_login_demo_user(page, demo["fixture"])
    bob = demo["fixture"]["users"][1]
    token = demo["tokens"][user["handle"]]["token"]
    page.goto(url("/"), wait_until="load")

    first_seen = {"count": 0}

    def delay_first(route):
        first_seen["count"] += 1
        if first_seen["count"] == 1:
            page.wait_for_timeout(600)
        route.continue_()

    page.route("**/me", delay_first)
    refresh = page.locator(tid("wallet-refresh"))
    refresh.click()  # slow, stale-by-the-time-it-arrives read #1

    changed = httpx.post(url("/payments"), json={"to_handle": bob["handle"], "amount": 123},
                         headers={**auth(token), "Idempotency-Key": unique("race")}, timeout=10)
    assert changed.status_code == 201, changed.text
    refresh.click()  # fast read #2, reflecting the real latest state

    page.wait_for_timeout(900)
    page.unroute("**/me", delay_first)
    final = page.locator(tid("wallet-balance")).get_attribute("data-amount")
    real = api_get("/me", headers=auth(token)).json()["total"]
    assert int(final) == real, "the stale, slower read must not win over the later, real state"
