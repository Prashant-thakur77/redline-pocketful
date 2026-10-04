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
    return fixture


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
                      settlement_operator_ids: list[str] | None = None):
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
                            settlement_operator_ids=settlement_operator_ids)
    reset_ok(fixture)
    return fixture, login_token(fixture["users"][0]["email"]), login_token(fixture["users"][1]["email"])


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
