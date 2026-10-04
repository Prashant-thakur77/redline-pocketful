"""Adversarial findings against N2-5 (the browser shell: R-2-090..093,
R-2-120..125), attacked at commit a357441.

BREACH: `service/ui/pages.py::_handle_signup` (the POST /signup FORM
handler, reached via `ui.try_handle` -> `pages.handle_post`) duplicates
the JSON `/auth/signup` endpoint's email/handle-uniqueness check-then-
insert logic, but does it directly against `STORE` with no
`STORE.write_lock()` at all — unlike `routes/auth.py::SignupEndpoint`,
whose own comment states the email/handle checks and the insert run "in
the same write-lock critical section... so two concurrent signups
racing on the same email or derived handle still produce exactly one
201 and one 409 (never two 201s)" (R-1-088). The UI path has no such
guarantee: concurrent form signups with the identical email all read
`email in STORE.users_by_email` as False before any of them writes,
and all proceed to create separate user records, all sharing the
seeded email and the same derived handle. Confirmed: 10 concurrent
POST /signup submissions with one email produced 10 distinct user
records, all with that email, all with the same handle, each with a
valid session cookie/token — not the "exactly one succeeds" guarantee
R-1-088 establishes for the JSON path.

The rest of this item's surface (R-1-089 cookie/JSON separation,
unauthenticated redirect to /login, a malformed session cookie, and
escaping of a user-controlled display_name) was also attacked and
holds; those are included below as regression coverage."""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import BASE_URL, unique  # noqa: E402


def _signup_form(email: str, password: str = "password123", display_name: str = "Attacker"):
    return httpx.post(BASE_URL + "/signup", data={"email": email, "password": password, "display_name": display_name},
                       headers={"Accept": "text/html"}, follow_redirects=False, timeout=10.0)


def test_concurrent_ui_signups_with_the_same_email_must_produce_exactly_one_account():
    """BREACH: ten concurrent POST /signup form submissions with the
    identical email must behave like the JSON endpoint — exactly one
    succeeds (302 redirect with a session), the rest see the
    'already registered' error page. The UI form handler currently has
    no write-lock around its check-then-insert, so this fails: all ten
    succeed, producing ten separate user records sharing one email and
    one derived handle (R-1-088's 'exactly one 201, never two' promise,
    violated for the form path)."""
    email = f"{unique('race')}@example.com"
    outs = []
    lock = threading.Lock()

    def do_signup():
        r = _signup_form(email)
        with lock:
            outs.append(r)

    threads = [threading.Thread(target=do_signup) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10.0)

    successes = [r for r in outs if r.status_code == 302]
    assert len(successes) == 1, (
        f"exactly one concurrent signup for the same email must succeed, got {len(successes)} of 10: "
        f"{[r.status_code for r in outs]}"
    )

    export = httpx.get(BASE_URL + "/_test/export", timeout=10.0).json()
    matching_users = [u for u in export["state"]["users"] if u["email"] == email]
    assert len(matching_users) == 1, (
        f"exactly one user record must exist for {email!r} after the race, found {len(matching_users)}: "
        f"{matching_users}"
    )


def test_cookie_never_authenticates_a_plain_json_request():
    """R-1-089: the session cookie issued by the UI's POST /signup must
    never authenticate a plain JSON endpoint — only a bearer token does."""
    email = f"{unique('cookiechk')}@example.com"
    r = _signup_form(email)
    assert r.status_code == 302, r.text
    cookie_val = r.headers.get("set-cookie", "").split(";")[0]

    r2 = httpx.get(BASE_URL + "/me", headers={"Cookie": cookie_val}, timeout=10.0)
    assert r2.status_code == 401, f"a UI session cookie must never authenticate /me: {r2.status_code} {r2.text}"


def test_unauthenticated_negotiated_page_redirects_to_login():
    """GET /requests with Accept: text/html and no session must redirect
    to /login, not error or leak data."""
    r = httpx.get(BASE_URL + "/requests", headers={"Accept": "text/html"}, follow_redirects=False, timeout=10.0)
    assert r.status_code == 302
    assert r.headers.get("location") == "/login"


def test_garbage_session_cookie_does_not_crash_negotiated_page():
    """A stale or forged cookie value must be treated as unauthenticated
    (redirect to /login), never a 500."""
    r = httpx.get(BASE_URL + "/requests", headers={"Accept": "text/html", "Cookie": "pocketful_session=not-a-real-token"},
                   follow_redirects=False, timeout=10.0)
    assert r.status_code != 500, f"a garbage session cookie must never 500: {r.status_code} {r.text}"
    assert r.status_code == 302 and r.headers.get("location") == "/login"


def test_display_name_with_markup_renders_escaped_not_raw():
    """A display_name containing HTML must never appear unescaped in the
    rendered page (stored-XSS check on the one user-controlled string
    `layout._user_chip_html` renders)."""
    evil_name = "<script>alert(1)</script>"
    email = f"{unique('xsschk')}@example.com"
    r = _signup_form(email, display_name=evil_name)
    assert r.status_code == 302, r.text
    cookie_val = r.headers.get("set-cookie", "").split(";")[0]

    r2 = httpx.get(BASE_URL + "/", headers={"Cookie": cookie_val}, timeout=10.0)
    assert "<script>alert(1)</script>" not in r2.text, "display_name must never render unescaped"
    assert "&lt;script&gt;" in r2.text


def test_api_client_preferring_json_is_unaffected_by_a_low_priority_html_accept():
    """BREACH: `ui._wants_html` is a naive substring check
    (`"text/html" in headers.get("accept", "")`), not a real Accept
    header parse. R-2-091 promises "existing API clients ... are
    unaffected" — a real client that primarily wants JSON but lists
    text/html as a near-zero-priority fallback (`Accept: application/
    json, text/html;q=0.01`, a realistic compound header) is exactly
    such a client, and it gets served the HTML page instead of JSON."""
    email = f"{unique('negjson')}@example.com"
    r = _signup_form(email)
    assert r.status_code == 302, r.text
    cookie_val = r.headers.get("set-cookie", "").split(";")[0]

    r2 = httpx.get(BASE_URL + "/requests", headers={
        "Cookie": cookie_val, "Accept": "application/json, text/html;q=0.01",
    }, timeout=10.0)
    assert "application/json" in r2.headers.get("content-type", ""), (
        f"a client that only nominally lists text/html at q=0.01 must still get JSON: "
        f"status={r2.status_code} content-type={r2.headers.get('content-type')}"
    )


def test_accept_header_substring_collision_does_not_falsely_trigger_html():
    """BREACH, same root cause: `"text/html" in accept` also matches
    Accept values that are not the `text/html` media type at all —
    `text/htmlx` and `application/text/html` both contain the
    substring without being it. Both wrongly divert to the UI."""
    email = f"{unique('negcollide')}@example.com"
    r = _signup_form(email)
    assert r.status_code == 302, r.text
    cookie_val = r.headers.get("set-cookie", "").split(";")[0]

    for bad_accept in ("text/htmlx", "application/text/html"):
        r2 = httpx.get(BASE_URL + "/requests", headers={"Cookie": cookie_val, "Accept": bad_accept}, timeout=10.0)
        assert "application/json" in r2.headers.get("content-type", ""), (
            f"Accept={bad_accept!r} is not text/html and must get JSON: "
            f"status={r2.status_code} content-type={r2.headers.get('content-type')}"
        )


def test_non_get_never_diverts_to_html_even_with_html_accept():
    """Non-GET requests must stay on the JSON API regardless of Accept
    (R-2-091 only negotiates GET)."""
    email = f"{unique('postneg')}@example.com"
    r = _signup_form(email)
    assert r.status_code == 302, r.text
    cookie_val = r.headers.get("set-cookie", "").split(";")[0]

    r2 = httpx.post(BASE_URL + "/requests", json={"payer_handle": "nobody", "amount": 1},
                     headers={"Cookie": cookie_val, "Accept": "text/html"}, timeout=10.0)
    assert "application/json" in r2.headers.get("content-type", "")
    r3 = httpx.post(BASE_URL + "/authorizations", json={"to_handle": "nobody", "amount": 1},
                     headers={"Cookie": cookie_val, "Accept": "text/html"}, timeout=10.0)
    assert "application/json" in r3.headers.get("content-type", "")


def test_cookie_invalidated_by_reset_degrades_to_clean_login_redirect():
    """A session cookie whose token was wiped by POST /_test/reset must
    redirect every authed route to /login, never 500 (R-1-005)."""
    email = f"{unique('staleafter')}@example.com"
    r = _signup_form(email)
    assert r.status_code == 302, r.text
    stale_cookie = r.headers.get("set-cookie", "").split(";")[0]

    reset_body = {"currency": "EUR", "minor_units": 2, "users": [
        {"id": unique("u"), "handle": unique("h"), "balance": 0,
         "email": f"{unique('fresh')}@example.com", "password": "password123", "display_name": "Fresh"},
    ]}
    rr = httpx.post(BASE_URL + "/_test/reset", json=reset_body, timeout=10.0)
    assert rr.status_code == 204, rr.text

    for path in ("/", "/split", "/requests", "/authorizations"):
        rp = httpx.get(BASE_URL + path, headers={"Cookie": stale_cookie, "Accept": "text/html"},
                        follow_redirects=False, timeout=10.0)
        assert rp.status_code != 500, f"{path} must never 500 on a cookie killed by reset: {rp.status_code}"
        assert rp.status_code == 302 and rp.headers.get("location") == "/login", (path, rp.status_code)
