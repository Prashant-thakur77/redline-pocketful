"""Browser product — the activity feed: R-2-131, R-2-132, R-2-106."""
from __future__ import annotations

from conftest import (api_post, auth, idem, make_fixture, reset_ok, tid, ui_login,
                      ui_login_demo_user, unique, unique_handle, url, user)


def test_activity_item_fields_for_a_seeded_public_payment(page, demo):
    """R-2-131"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    seeded_id = "p-seed-1"  # alice -> bob, 500, public, note "lunch"
    item = page.locator(tid(f"activity-item-{seeded_id}"))
    assert item.count() > 0
    assert item.get_attribute("data-visibility") == "public"
    parties = page.locator(tid(f"activity-parties-{seeded_id}"))
    text = parties.inner_text()
    assert "alice" in text and "bob" in text
    amount_el = page.locator(tid(f"activity-amount-{seeded_id}"))
    assert amount_el.inner_text().strip() == "5.00 EUR"
    note_el = page.locator(tid(f"activity-note-{seeded_id}"))
    assert note_el.inner_text().strip() == "lunch"


def test_activity_note_element_present_even_when_empty(page, demo):
    """R-2-131"""
    user = ui_login_demo_user(page, demo["fixture"])
    bob = demo["fixture"]["users"][1]
    token = demo["tokens"][user["handle"]]["token"]
    r = api_post("/payments", json={"to_handle": bob["handle"], "amount": 50},
                 headers={**auth(token), **idem(unique("no-note"))})
    assert r.status_code == 201, r.text
    payment_id = r.json()["payment_id"]
    page.goto(url("/"), wait_until="load")
    note_el = page.locator(tid(f"activity-note-{payment_id}"))
    assert note_el.count() > 0
    assert note_el.inner_text().strip() == ""


def test_empty_activity_marker_when_nothing_visible(page):
    """R-2-131"""
    a_id, b_id = unique("u"), unique("u")
    fixture = make_fixture([user(a_id, unique_handle("a"), balance=100), user(b_id, unique_handle("b"), balance=0)])
    reset_ok(fixture)
    ui_login(page, fixture["users"][0]["email"], fixture["users"][0]["password"])
    page.goto(url("/"), wait_until="load")
    assert page.locator(tid("empty-activity")).count() > 0
    assert page.locator(tid("activity-list")).count() == 0 or \
        page.locator(f'{tid("activity-list")} > *').count() == 0


def test_activity_newest_first_in_dom(page, demo):
    """R-2-131, R-2-132: newest first in the DOM; ties within the same
    second may appear in either order, so this only orders payments created
    with a deliberate gap, never asserting on same-second ties."""
    user = ui_login_demo_user(page, demo["fixture"])
    bob = demo["fixture"]["users"][1]
    token = demo["tokens"][user["handle"]]["token"]
    ids = []
    for i in range(3):
        r = api_post("/payments", json={"to_handle": bob["handle"], "amount": 1},
                     headers={**auth(token), **idem(unique(f"order{i}"))})
        assert r.status_code == 201, r.text
        ids.append(r.json()["payment_id"])
        page.wait_for_timeout(1100)  # clear any same-second tie (R-2-132)

    page.goto(url("/"), wait_until="load")
    dom_ids = page.eval_on_selector_all(
        f'{tid("activity-list")} > *',
        "els => els.map(e => e.getAttribute('data-testid'))",
    )
    positions = [dom_ids.index(f"activity-item-{pid}") for pid in ids if f"activity-item-{pid}" in dom_ids]
    # ids are in creation order (oldest first); newest-first DOM order means
    # each later-created payment has a SMALLER DOM index than an earlier one.
    assert positions == sorted(positions, reverse=True), \
        f"newest-created payments must appear first (lowest DOM index): {positions}"


def test_parties_show_handles_not_internal_ids(page, demo):
    """R-2-106: people are formatted for people first — handles, not raw
    internal user ids, appear in the activity list."""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    parties_text = page.locator(tid("activity-parties-p-seed-1")).inner_text()
    assert "u-alice" not in parties_text and "u-bob" not in parties_text
