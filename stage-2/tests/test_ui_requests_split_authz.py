"""Browser product — /requests, /split and /authorizations screens:
R-2-130, R-2-133..138."""
from __future__ import annotations

from conftest import api_get, api_post, auth, idem, login_token, tid, ui_login_demo_user, unique, url


def test_request_form_testids(page, demo):
    """R-2-130"""
    ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/"), wait_until="load")
    for field in ("request-handle", "request-amount", "request-note", "request-submit"):
        assert page.locator(tid(field)).count() > 0, f"missing {field}"


def test_requests_screen_lists_and_testids(page, demo):
    """R-2-133"""
    user = ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/requests"), wait_until="load")
    assert page.locator(tid("incoming-list")).count() > 0
    assert page.locator(tid("outgoing-list")).count() > 0
    # the demo fixture seeds alice as requester of r-seed-1 (outgoing, pending)
    seeded_outgoing_id = "r-seed-1"
    item = page.locator(tid(f"request-item-{seeded_outgoing_id}"))
    assert item.count() > 0
    assert item.get_attribute("data-status") == "pending"
    amount_el = page.locator(tid(f"request-amount-{seeded_outgoing_id}"))
    assert amount_el.inner_text().strip() == "3.00 EUR"


def test_request_actions_present_only_on_correct_side_and_status(page, demo):
    """R-2-134"""
    user = ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/requests"), wait_until="load")
    # r-seed-1: alice is requester (outgoing, pending) -> cancel only, no pay/decline
    assert page.locator(tid("request-cancel-r-seed-1")).count() > 0
    assert page.locator(tid("request-pay-r-seed-1")).count() == 0
    assert page.locator(tid("request-decline-r-seed-1")).count() == 0

    # r-seed-5: alice is payer, status paid (terminal) -> no actions at all
    assert page.locator(tid("request-pay-r-seed-5")).count() == 0
    assert page.locator(tid("request-decline-r-seed-5")).count() == 0
    assert page.locator(tid("request-cancel-r-seed-5")).count() == 0


def test_split_form_testids_and_preview(page, demo):
    """R-2-135, R-2-136"""
    user = ui_login_demo_user(page, demo["fixture"])
    bob = demo["fixture"]["users"][1]
    page.goto(url("/split"), wait_until="load")
    for field in ("split-amount", "split-handles", "split-note", "split-submit"):
        assert page.locator(tid(field)).count() > 0, f"missing {field}"

    page.fill(tid("split-amount"), "10.00")
    page.fill(tid("split-handles"), f"{user['handle']},{bob['handle']}")
    page.wait_for_timeout(300)

    preview = page.locator(tid("split-preview"))
    assert preview.count() > 0
    share_a = page.locator(tid(f"split-share-{user['handle']}"))
    share_b = page.locator(tid(f"split-share-{bob['handle']}"))
    assert share_a.count() > 0 and share_b.count() > 0
    # 1000 minor units / 2 participants -> 500 each, by R-1-173's base/rem rule
    assert share_a.inner_text().strip() == "5.00 EUR"
    assert share_b.inner_text().strip() == "5.00 EUR"

    token = user["token"]
    before = api_get("/requests", headers=auth(token), params={"direction": "outgoing"}).json()["requests"]
    page.click(tid("split-submit"))
    page.wait_for_timeout(500)
    after = api_get("/requests", headers=auth(token), params={"direction": "outgoing"}).json()["requests"]
    new_requests = [r for r in after if r["request_id"] not in {x["request_id"] for x in before}]
    assert len(new_requests) == 1, f"the split must create exactly one new request for bob: {new_requests}"
    assert new_requests[0]["amount"] == 500, "the submitted split's share must match the preview's share"


def test_authorizations_screen_testids(page, demo):
    """R-2-137"""
    user = ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/authorizations"), wait_until="load")
    assert page.locator(tid("authorization-list")).count() > 0
    seeded_captured = "a-seed-captured"
    item = page.locator(tid(f"authorization-item-{seeded_captured}"))
    assert item.count() > 0
    assert item.get_attribute("data-status") == "captured"
    assert page.locator(tid(f"authorization-amount-{seeded_captured}")).inner_text().strip() == "5.00 EUR"
    captured_el = page.locator(tid(f"authorization-captured-{seeded_captured}"))
    assert captured_el.count() > 0
    assert captured_el.inner_text().strip() == "5.00 EUR"
    expires_el = page.locator(tid(f"authorization-expires-{seeded_captured}"))
    assert expires_el.count() > 0
    assert expires_el.inner_text().strip() != ""


def test_authorization_captured_field_absent_unless_captured(page, demo):
    """R-2-137"""
    user = ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/authorizations"), wait_until="load")
    seeded_open = "a-seed-open-out"
    assert page.locator(tid(f"authorization-captured-{seeded_open}")).count() == 0


def test_capture_void_buttons_present_only_on_correct_side(page, demo):
    """R-2-138"""
    user = ui_login_demo_user(page, demo["fixture"])
    page.goto(url("/authorizations"), wait_until="load")
    # a-seed-open-out: alice is the PAYER (outgoing) -> void only, no capture
    assert page.locator(tid("authorization-void-a-seed-open-out")).count() > 0
    assert page.locator(tid("authorization-capture-a-seed-open-out")).count() == 0

    # a-seed-open-in: alice is the RECEIVER (incoming) -> capture only, no void
    assert page.locator(tid("authorization-capture-a-seed-open-in")).count() > 0
    assert page.locator(tid("authorization-void-a-seed-open-in")).count() == 0
    prefill = page.locator(tid("authorization-capture-amount-a-seed-open-in"))
    assert prefill.count() > 0
    assert prefill.input_value() in ("8.00", "8")


def test_request_cancelled_elsewhere_shows_error_and_removes_stale_pay_button(page, demo):
    """R-2-156"""
    alice = ui_login_demo_user(page, demo["fixture"])
    bob = demo["fixture"]["users"][1]
    bob_token = login_token(bob["email"], bob["password"])

    req = api_post("/requests", json={"payer_handle": alice["handle"], "amount": 50},
                   headers={**auth(bob_token), **idem(unique("k"))})
    assert req.status_code == 201, req.text
    req_id = req.json()["request_id"]

    page.goto(url("/requests"), wait_until="load")
    pay_button = page.locator(tid(f"request-pay-{req_id}"))
    assert pay_button.count() > 0, "the pay button must be visible before the stale-state race"

    cancelled = api_post(f"/requests/{req_id}/cancel", json={}, headers=auth(bob_token))
    assert cancelled.status_code == 200, cancelled.text

    pay_button.click()
    page.wait_for_timeout(500)
    assert page.locator(tid("request-error")).count() > 0
    assert page.locator(tid(f"request-pay-{req_id}")).count() == 0, \
        "the list must refresh so the stale pay button disappears"
