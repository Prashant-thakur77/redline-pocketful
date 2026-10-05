from __future__ import annotations

import itertools
import os
import sys
import uuid
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from demo_fixture import build_demo_fixture  # noqa: E402

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:8080").rstrip("/")
TIMEOUT = 10.0

_run_id = uuid.uuid4().hex[:8]
_seq = itertools.count()


def unique(prefix: str = "x") -> str:
    return f"{prefix}{_run_id}{next(_seq)}"


def unique_email(prefix: str = "user") -> str:
    return f"{unique(prefix)}@example.com"


def unique_handle(prefix: str = "h") -> str:
    # lowercase letters + digits only, matches ^[a-z0-9_]{1,20}$
    h = f"{prefix}{_run_id}{next(_seq)}".lower()
    return h[:20]


def url(path: str) -> str:
    return BASE_URL + path


def api_get(path: str, headers: dict | None = None, params: dict | None = None, timeout: float = TIMEOUT):
    return httpx.get(url(path), headers=headers, params=params, timeout=timeout)


def api_post(path: str, json=None, headers: dict | None = None, params: dict | None = None,
             content: bytes | None = None, timeout: float = TIMEOUT):
    if content is not None:
        return httpx.post(url(path), content=content, headers=headers, params=params, timeout=timeout)
    return httpx.post(url(path), json=json, headers=headers, params=params, timeout=timeout)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def idem(key: str) -> dict:
    return {"Idempotency-Key": key}


def auth_idem(token: str, key: str) -> dict:
    return {**auth(token), **idem(key)}


def reset(fixture: dict) -> httpx.Response:
    r = api_post("/_test/reset", json=fixture)
    return r


def reset_ok(fixture: dict) -> httpx.Response:
    r = reset(fixture)
    assert r.status_code == 204, f"reset failed: {r.status_code} {r.text}"
    return r


def user(id: str, handle: str, balance: int = 0, email: str | None = None,
         password: str = "password123", display_name: str | None = None) -> dict:
    return {
        "id": id,
        "email": email or f"{handle}@example.com",
        "password": password,
        "display_name": display_name or handle.title(),
        "handle": handle,
        "balance": balance,
    }


def make_fixture(users: list[dict], payments: list[dict] | None = None,
                  requests: list[dict] | None = None,
                  settlement_operator_ids: list[str] | None = None,
                  authorizations: list[dict] | None = None,
                  authorization_ttl_seconds: int | None = None,
                  currency: str = "EUR", minor_units: int = 2) -> dict:
    fixture = {
        "currency": currency,
        "minor_units": minor_units,
        "users": users,
    }
    if payments is not None:
        fixture["payments"] = payments
    if requests is not None:
        fixture["requests"] = requests
    if settlement_operator_ids is not None:
        fixture["settlement_operator_ids"] = settlement_operator_ids
    if authorizations is not None:
        fixture["authorizations"] = authorizations
    if authorization_ttl_seconds is not None:
        fixture["authorization_ttl_seconds"] = authorization_ttl_seconds
    return fixture


def authorization(id: str, from_user_id: str, to_user_id: str, amount: int, note: str = "",
                   visibility: str = "public", status: str = "open", expires_at: str | None = None,
                   captured_amount: int | None = None) -> dict:
    from datetime import datetime, timedelta, timezone
    entry = {
        "id": id, "from_user_id": from_user_id, "to_user_id": to_user_id, "amount": amount,
        "note": note, "visibility": visibility, "status": status,
        "expires_at": expires_at or (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
    }
    if captured_amount is not None:
        entry["captured_amount"] = captured_amount
    return entry


def login(email: str, password: str) -> httpx.Response:
    return api_post("/auth/login", json={"email": email, "password": password})


def login_token(email: str, password: str = "password123") -> str:
    r = login(email, password)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text}"
    return r.json()["token"]


def signup(email: str | None = None, password: str = "password123",
           display_name: str = "Test User") -> httpx.Response:
    email = email or unique_email()
    return api_post("/auth/signup", json={"email": email, "password": password, "display_name": display_name})


def signup_ok(email: str | None = None, password: str = "password123",
              display_name: str = "Test User") -> dict:
    email = email or unique_email()
    r = signup(email, password, display_name)
    assert r.status_code == 201, f"signup failed: {r.status_code} {r.text}"
    body = r.json()
    return {"user_id": body["user_id"], "token": body["token"], "display_name": body["display_name"], "email": email}


@pytest.fixture
def two_users():
    """A fresh two-user fixture: alice (balance 10000) and bob (balance 0).
    Used by @adversary's suite via pytest fixture injection — keep this
    signature and these balances stable; it is not this file's helper to
    change the defaults of (see two_user_fixture below for that one)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("alice"), unique_handle("bob")
    fixture = make_fixture([
        user(a_id, a_handle, balance=10_000),
        user(b_id, b_handle, balance=0),
    ])
    reset_ok(fixture)
    a_token = login_token(fixture["users"][0]["email"])
    b_token = login_token(fixture["users"][1]["email"])
    return {
        "fixture": fixture,
        "a": {"id": a_id, "handle": a_handle, "token": a_token, "email": fixture["users"][0]["email"]},
        "b": {"id": b_id, "handle": b_handle, "token": b_token, "email": fixture["users"][1]["email"]},
    }


def two_user_fixture(balance_a: int = 10_000, balance_b: int = 10_000,
                      settlement_operator_ids: list[str] | None = None,
                      authorizations: list[dict] | None = None,
                      authorization_ttl_seconds: int | None = None):
    """The one shared two-user fixture used as a plain function call (not
    pytest-fixture injection) across several test files.

    Both users are funded by default so EITHER may act as payer without
    hitting insufficient_funds by accident; a test whose point is a broke
    payer overrides balance_a/balance_b explicitly. This used to be copied
    locally into four test files with drifting defaults (one copy left
    balance_b at 0), which is exactly how N1-T.5 happened twice — fixing one
    copy and not the other. One function, one default, fixed everywhere.
    """
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=balance_a), user(b_id, b_handle, balance=balance_b)],
                            settlement_operator_ids=settlement_operator_ids,
                            authorizations=authorizations, authorization_ttl_seconds=authorization_ttl_seconds)
    reset_ok(fixture)
    return fixture, login_token(fixture["users"][0]["email"]), login_token(fixture["users"][1]["email"])


def n_user_fixture(n: int, balance: int = 10_000, operator_indexes: list[int] | None = None,
                    authorization_ttl_seconds: int | None = None):
    """A generic N-user fixture as a plain function call, shared across stage-2
    test files that need more than two participants (e.g. capture-by-receiver
    vs. a third party). One function, so a drifting default can't be copied
    into only some of its callers (see two_user_fixture's docstring).

    `operator_indexes` names settlement operators by position (0-based, into
    the same `n` participants) rather than by id, because the ids are
    generated inside this function — a caller cannot know them in advance to
    pass as `settlement_operator_ids` directly."""
    ids = [unique("u") for _ in range(n)]
    handles = [unique_handle(f"p{i}") for i in range(n)]
    operator_ids = [ids[i] for i in operator_indexes] if operator_indexes is not None else None
    fixture = make_fixture([user(ids[i], handles[i], balance=balance) for i in range(n)],
                            settlement_operator_ids=operator_ids,
                            authorization_ttl_seconds=authorization_ttl_seconds)
    reset_ok(fixture)
    tokens = [login_token(fixture["users"][i]["email"]) for i in range(n)]
    return fixture, ids, handles, tokens


@pytest.fixture
def demo():
    """Reset to the shared demo fixture and log every seeded user in."""
    fixture = build_demo_fixture()
    reset_ok(fixture)
    tokens = {}
    for u in fixture["users"]:
        tokens[u["handle"]] = {"token": login_token(u["email"], u["password"]), "user_id": u["id"]}
    return {"fixture": fixture, "tokens": tokens}


def error_code(resp: httpx.Response) -> str:
    body = resp.json()
    return body["error"]["code"]


def assert_error(resp: httpx.Response, status: int, code: str):
    assert resp.status_code == status, f"expected {status} got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "error" in body and isinstance(body["error"], dict), f"malformed error body: {resp.text}"
    assert body["error"].get("code") == code, f"expected code {code} got {body['error'].get('code')}: {resp.text}"
    assert isinstance(body["error"].get("message"), str) and body["error"]["message"], \
        f"error message must be a non-empty string: {resp.text}"


def open_authorization(payer_token: str, receiver_handle: str, amount: int = 1000, **kw) -> dict:
    """Create an authorization as `payer_token`'s owner, to `receiver_handle`.
    Shared across every stage-2 test file that needs one, so a drifting copy
    cannot be left behind in only some of them (the N1-T.5 lesson)."""
    r = api_post("/authorizations", json={"to_handle": receiver_handle, "amount": amount, **kw},
                 headers={**auth(payer_token), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    return r.json()


# ---------------------------------------------------------------------------
# Browser fixtures — pytest-playwright is not installed, only the raw
# `playwright` package, so the `browser`/`page` fixtures below are hand-rolled
# rather than coming from a plugin. Shared here so no UI test file reinvents
# them (the same duplicated-helper hazard as the API-side fixtures).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    pg = context.new_page()
    yield pg
    context.close()


def tid(name: str) -> str:
    return f'[data-testid="{name}"]'


# ---------------------------------------------------------------------------
# Condition-based UI waits — replace a fixed `page.wait_for_timeout(N)` after
# an action with a wait on the actual completion signal, so the test is both
# deterministic and no slower than it has to be. A fixed sleep after a
# submit races the write it is meant to wait for under load (see N4-H2); use
# ONE of these instead, matching whatever the test actually depends on:
#   - the response to the triggering request (wait_for_response_to)
#   - a DOM element appearing/disappearing (wait_for_present/wait_for_absent)
#   - an observed value changing, e.g. a balance (wait_for_dom_change)
# ---------------------------------------------------------------------------

def wait_for_response_to(page, action, method: str = "POST", path_suffix: str = "/payments", timeout_ms: int = 5000):
    """Run `action()` and wait for the matching HTTP response to complete.
    Only valid when the browser actually receives a response — a request
    whose route is deliberately aborted (route.abort()) never fires one;
    use wait_for_present/absent on the resulting DOM state instead."""
    with page.expect_response(
        lambda r: r.request.method == method and r.url.endswith(path_suffix),
        timeout=timeout_ms,
    ) as resp_info:
        action()
    return resp_info.value


def wait_for_present(page, selector: str, timeout_ms: int = 5000) -> None:
    page.wait_for_function("(sel) => document.querySelector(sel) !== null", arg=selector, timeout=timeout_ms)


def wait_for_absent(page, selector: str, timeout_ms: int = 5000) -> None:
    page.wait_for_function("(sel) => document.querySelector(sel) === null", arg=selector, timeout=timeout_ms)


def wait_for_dom_change(page, selector: str, before_value: str, attr: str | None = None, timeout_ms: int = 5000) -> None:
    """Wait until `selector`'s text (or `attr`, if given) differs from
    `before_value`. `before_value` must be read BEFORE the triggering
    action, from the same property this then polls."""
    if attr:
        page.wait_for_function(
            "([sel, name, before]) => document.querySelector(sel)?.getAttribute(name) !== before",
            arg=[selector, attr, before_value],
            timeout=timeout_ms,
        )
    else:
        page.wait_for_function(
            "([sel, before]) => document.querySelector(sel)?.innerText.trim() !== before",
            arg=[selector, before_value.strip()],
            timeout=timeout_ms,
        )


def ui_signup(page, email: str, password: str, display_name: str) -> None:
    page.goto(url("/signup"), wait_until="load")
    page.fill(tid("signup-email"), email)
    page.fill(tid("signup-password"), password)
    page.fill(tid("signup-display-name"), display_name)
    page.click(tid("signup-submit"))
    page.wait_for_load_state("load")


def ui_login(page, email: str, password: str) -> None:
    page.goto(url("/login"), wait_until="load")
    page.fill(tid("login-email"), email)
    page.fill(tid("login-password"), password)
    page.click(tid("login-submit"))
    page.wait_for_load_state("load")


def ui_login_demo_user(page, fixture: dict, index: int = 0) -> dict:
    """Reset to `fixture` and log the UI in as `fixture["users"][index]`.

    Returns the user dict with a LIVE `"token"` key obtained after this
    function's own reset — any token a caller captured earlier (e.g. from
    the `demo` pytest fixture, which does its own separate reset+login
    before a test body runs) is invalidated by the `reset_ok` above and
    must not be reused. Callers that need an API token for this user should
    read it from the returned dict, not from a `demo["tokens"][...]` lookup
    made before this call.
    """
    reset_ok(fixture)
    u = fixture["users"][index]
    ui_login(page, u["email"], u["password"])
    return {**u, "token": login_token(u["email"], u["password"])}
