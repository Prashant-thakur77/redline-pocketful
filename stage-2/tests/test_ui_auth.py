"""Browser product — routes, shared paths, signup/login, and the
data-testid identity contract: R-2-090..093, R-2-120..125."""
from __future__ import annotations

from urllib.parse import urlparse

from conftest import BASE_URL, api_get, tid, ui_login, ui_login_demo_user, ui_signup, unique_email, url

ROUTES = ["/", "/requests", "/split", "/signup", "/login", "/authorizations"]


def test_every_required_route_reachable(page, demo):
    """R-2-090"""
    ui_login_demo_user(page, demo["fixture"])
    for route in ROUTES:
        response = page.goto(url(route), wait_until="load")
        assert response is not None and response.status < 400, f"{route}: {response.status if response else 'no response'}"


def test_requests_and_authorizations_shared_html_json(page, demo):
    """R-2-091: Accept: text/html gets the UI; no Accept / application/json
    gets JSON, and existing API clients are unaffected."""
    user = ui_login_demo_user(page, demo["fixture"])
    token = user["token"]

    html_resp = api_get("/requests", headers={"Authorization": f"Bearer {token}", "Accept": "text/html"})
    assert html_resp.status_code == 200
    assert "text/html" in html_resp.headers.get("content-type", "")

    json_resp = api_get("/requests", headers={"Authorization": f"Bearer {token}"})
    assert json_resp.status_code == 200
    assert json_resp.headers.get("content-type", "").startswith("application/json")
    assert "requests" in json_resp.json()

    explicit_json = api_get("/requests", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    assert explicit_json.status_code == 200
    assert "requests" in explicit_json.json()


def test_no_external_network_request(page, demo):
    """R-2-092: every runtime asset is served from the image."""
    ui_login_demo_user(page, demo["fixture"])
    host = urlparse(BASE_URL).netloc
    external = []
    page.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc in (host, "")
               else (external.append(route.request.url), route.abort()))
    for route in ROUTES:
        page.goto(url(route), wait_until="load")
    assert external == [], f"external request(s) made: {external}"


def test_current_user_visible_on_every_screen(page, demo):
    """R-2-093, R-2-123, R-2-124"""
    user = ui_login_demo_user(page, demo["fixture"])
    for route in ("/", "/requests", "/authorizations", "/split"):
        page.goto(url(route), wait_until="load")
        current_user = page.locator(tid("current-user"))
        assert current_user.count() > 0, f"{route}: no current-user element"
        assert user["display_name"] in current_user.inner_text()
        current_handle = page.locator(tid("current-handle"))
        assert current_handle.inner_text().strip() == user["handle"]


def test_signup_fields_and_flow(page):
    """R-2-120"""
    email = unique_email("uisignup")
    page.goto(url("/signup"), wait_until="load")
    for field in ("signup-email", "signup-password", "signup-display-name", "signup-submit"):
        assert page.locator(tid(field)).count() > 0, f"missing {field}"
    ui_signup(page, email, "password123", "UI Signup Person")
    assert page.locator(tid("current-user")).count() > 0


def test_login_fields_and_flow(page, demo):
    """R-2-121"""
    page.goto(url("/login"), wait_until="load")
    for field in ("login-email", "login-password", "login-submit"):
        assert page.locator(tid(field)).count() > 0, f"missing {field}"
    reset_user = demo["fixture"]["users"][0]
    ui_login(page, reset_user["email"], reset_user["password"])
    assert page.locator(tid("current-user")).count() > 0


def test_auth_error_present_only_when_there_is_one(page, demo):
    """R-2-122"""
    page.goto(url("/login"), wait_until="load")
    assert page.locator(tid("auth-error")).count() == 0
    ui_login(page, "no-such-user@example.com", "wrong-password")
    assert page.locator(tid("auth-error")).count() > 0
    assert page.locator(tid("auth-error")).inner_text().strip() != ""


def test_logout_button_present_and_signs_out(page, demo):
    """R-2-125"""
    ui_login_demo_user(page, demo["fixture"])
    logout = page.locator(tid("logout-button"))
    assert logout.count() > 0
    logout.click()
    page.wait_for_load_state("load")
    page.goto(url("/"), wait_until="load")
    assert page.locator(tid("login-email")).count() > 0 or page.locator(tid("current-user")).count() == 0
