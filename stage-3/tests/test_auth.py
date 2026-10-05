"""Authentication: R-1-034..037, R-1-080..092."""
from __future__ import annotations

import re

from conftest import (api_get, api_post, assert_error, auth, idem, login, login_token, make_fixture,
                       reset_ok, signup, signup_ok, unique, unique_email, unique_handle, user)


def test_signup_creates_usable_account():
    """R-1-080"""
    email = unique_email("newbie")
    r = signup(email, "password123", "New Person")
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body.keys()) >= {"user_id", "display_name", "token"}
    assert body["display_name"] == "New Person"
    me = api_get("/me", headers=auth(body["token"]))
    assert me.status_code == 200
    assert me.json()["balance"] == 0


def test_signup_derived_handle_from_email_local_part():
    """R-1-036"""
    email = f"My.Weird+Name_{unique('x')}@example.com"
    r = signup(email, "password123", "Weird Name")
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    me = api_get("/me", headers=auth(token))
    handle = me.json()["handle"]
    local = email.split("@", 1)[0]
    expected = re.sub(r"[^a-z0-9_]", "_", local.lower())[:20]
    assert handle == expected
    assert re.match(r"^[a-z0-9_]{1,20}$", handle)


def test_signup_ignores_supplied_handle_field():
    """R-1-081, R-1-022"""
    email = unique_email("ignorehandle")
    r = api_post("/auth/signup", json={"email": email, "password": "password123",
                                        "display_name": "X", "handle": "totally_different"})
    assert r.status_code == 201, r.text
    token = r.json()["token"]
    me = api_get("/me", headers=auth(token))
    assert me.json()["handle"] != "totally_different"


def test_login_with_correct_password():
    """R-1-082"""
    email = unique_email("loginok")
    signup_ok(email, "password123", "Login OK")
    r = login(email, "password123")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"user_id", "display_name", "token"}


def test_signup_duplicate_email_409():
    """R-1-083"""
    email = unique_email("dupemail")
    signup_ok(email, "password123", "First")
    r = signup(email, "password123", "Second")
    assert_error(r, 409, "email_taken")


def test_signup_short_password_422():
    """R-1-084"""
    r = signup(unique_email("shortpw"), "short1", "X")
    assert_error(r, 422, "validation_failed")


def test_signup_invalid_email_422():
    """R-1-085"""
    for bad in ("@example.com", "noatsign.com", "local@"):
        r = signup(bad, "password123", "X")
        assert_error(r, 422, "validation_failed")


def test_login_wrong_password_401():
    """R-1-086"""
    email = unique_email("wrongpw")
    signup_ok(email, "password123", "X")
    r = login(email, "wrong-password")
    assert_error(r, 401, "unauthenticated")


def test_login_unknown_email_401_same_as_wrong_password():
    """R-1-086"""
    r = login(unique_email("neverexisted"), "whatever123")
    assert_error(r, 401, "unauthenticated")


def test_signup_handle_collision_with_existing_account_409():
    """R-1-087"""
    local = unique("collide")
    email1 = f"{local}@example.com"
    signup_ok(email1, "password123", "First")
    # a different email whose derived handle collides (case/char folding both map to same handle)
    email2 = f"{local.upper()}@other.com"
    r = signup(email2, "password123", "Second")
    assert_error(r, 409, "handle_taken")


def test_signup_precedence_validation_before_email_before_handle():
    """R-1-088"""
    email = unique_email("precedence")
    signup_ok(email, "password123", "First")
    # same email again: must be email_taken, never handle_taken, even though handle would also collide
    r = signup(email, "password123", "Second")
    assert_error(r, 409, "email_taken")


def test_protected_endpoint_requires_bearer_token():
    """R-1-089"""
    r = api_get("/me")
    assert_error(r, 401, "unauthenticated")


def test_public_endpoints_need_no_auth():
    """R-1-089"""
    assert api_get("/health").status_code == 200
    assert api_post("/auth/login", json={"email": "nope@example.com", "password": "x"}).status_code in (401, 422)


def test_tokens_never_expire_and_multiple_concurrent_tokens_valid():
    """R-1-090"""
    email = unique_email("multitoken")
    signup_ok(email, "password123", "Multi")
    t1 = login_token(email)
    t2 = login_token(email)
    assert t1 != t2 or True  # tokens may or may not differ in value, but both must work:
    assert api_get("/me", headers=auth(t1)).status_code == 200
    assert api_get("/me", headers=auth(t2)).status_code == 200


def test_password_not_stored_in_plaintext_via_export():
    """R-1-091"""
    email = unique_email("hashcheck")
    plaintext = "password123"
    signup_ok(email, plaintext, "Hash Check")
    export = api_get("/_test/export")
    assert export.status_code == 200
    raw = export.text
    assert plaintext not in raw, "plaintext password must never appear in exported state"


def test_token_prefix_suffix_case_variants_rejected():
    """R-1-092"""
    email = unique_email("tokenvariant")
    signup_ok(email, "password123", "Variant")
    token = login_token(email)
    variants = [token[:-1], token + "x", token.upper() if token.upper() != token else token.lower()]
    for v in variants:
        if v == token:
            continue
        r = api_get("/me", headers=auth(v))
        assert_error(r, 401, "unauthenticated")


def test_missing_authorization_header():
    """R-1-063"""
    r = api_get("/me", headers={})
    assert_error(r, 401, "unauthenticated")


def test_authorization_header_not_bearer_form():
    """R-1-063"""
    r = api_get("/me", headers={"Authorization": "Basic abcdef"})
    assert_error(r, 401, "unauthenticated")


def test_authorization_header_unknown_token():
    """R-1-063"""
    r = api_get("/me", headers={"Authorization": "Bearer totally-made-up-token-value"})
    assert_error(r, 401, "unauthenticated")


def test_signup_handle_collision_via_different_special_chars_409():
    """R-1-088: two different emails whose local parts normalize to the same
    handle (a dot and an underscore both fold to '_') must collide, even
    though the raw emails and the characters that triggered the fold differ."""
    tag = unique("")
    first_email = f"a_b_{tag}@x.com"
    second_email = f"a.b_{tag}@x.com"
    signup_ok(first_email, "password123", "First")
    r = signup(second_email, "password123", "Second")
    assert_error(r, 409, "handle_taken")


def test_login_unknown_email_and_wrong_password_identical_response():
    """R-1-086a: the observable contract — both cases are 401 unauthenticated
    with an IDENTICAL response body; no field distinguishes an unknown email
    from a wrong password (the timing side of this is @adversary's)."""
    known_email = unique_email("knownuser")
    signup_ok(known_email, "password123", "Known User")
    wrong_password = login(known_email, "definitely-the-wrong-password")
    unknown_email = login(unique_email("neverexisted"), "whatever-password-123")
    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
