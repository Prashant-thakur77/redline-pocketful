"""Page bodies and form handlers for the six required routes (R-2-090) plus
signup/login/logout (R-2-120..125). `/` and `/split` ship chrome and a
considered empty state only — their real content is N2-6/N2-7's scope;
`/requests` and `/authorizations` here likewise render chrome plus an
honest empty-or-not-yet-built state, never a stored `held`/`available`
number, since neither screen's real listing exists yet.
"""
from __future__ import annotations

import secrets

from ..handles import derive_handle
from ..json_utils import dumps
from ..passwords import DUMMY_PASSWORD_HASH, hash_password, verify_password
from ..store import STORE
from . import assets
from .layout import esc, render_shell

_HTML_HEADERS = [("Content-Type", "text/html; charset=utf-8")]
_MIN_PASSWORD_LEN = 8


def serve_static(path: str):
    name = path[len("/static/"):]
    content = assets.FILES.get(name)
    if content is None:
        body = dumps({"error": {"code": "not_found", "message": "no such asset"}})
        return 404, [("Content-Type", "application/json; charset=utf-8")], body
    return 200, [("Content-Type", assets.CONTENT_TYPES[name])], content


def _redirect(location: str, *, set_cookie: str | None = None):
    headers = [("Location", location)]
    if set_cookie is not None:
        headers.append(("Set-Cookie", set_cookie))
    return 302, headers, b""


def _session_cookie(token: str) -> str:
    return f"pocketful_session={token}; HttpOnly; Path=/; SameSite=Lax"


def _clear_session_cookie() -> str:
    return "pocketful_session=; HttpOnly; Path=/; SameSite=Lax; Max-Age=0"


# ---------------------------------------------------------------------------
# public pages: signup, login
# ---------------------------------------------------------------------------

def _error_html(message: str | None) -> str:
    if not message:
        return ""
    return f'<p class="form-error" data-testid="auth-error">{esc(message)}</p>'


def _login_body(error: str | None) -> str:
    return f"""<section class="auth-card">
  <h1>Log in</h1>
  {_error_html(error)}
  <form method="POST" action="/login" class="form">
    <label class="field">
      <span class="field-label">Email</span>
      <input type="email" name="email" data-testid="login-email" autocomplete="username" required>
    </label>
    <label class="field">
      <span class="field-label">Password</span>
      <input type="password" name="password" data-testid="login-password" autocomplete="current-password" required>
    </label>
    <button type="submit" data-testid="login-submit" class="btn btn-primary">Log in</button>
  </form>
  <p class="auth-switch">No account? <a href="/signup">Sign up</a></p>
</section>"""


def _signup_body(error: str | None) -> str:
    return f"""<section class="auth-card">
  <h1>Sign up</h1>
  {_error_html(error)}
  <form method="POST" action="/signup" class="form">
    <label class="field">
      <span class="field-label">Email</span>
      <input type="email" name="email" data-testid="signup-email" autocomplete="username" required>
    </label>
    <label class="field">
      <span class="field-label">Password</span>
      <input type="password" name="password" data-testid="signup-password" autocomplete="new-password" required>
    </label>
    <label class="field">
      <span class="field-label">Display name</span>
      <input type="text" name="display_name" data-testid="signup-display-name" autocomplete="name" required>
    </label>
    <button type="submit" data-testid="signup-submit" class="btn btn-primary">Sign up</button>
  </form>
  <p class="auth-switch">Already have an account? <a href="/login">Log in</a></p>
</section>"""


def render_public_page(path: str, user: dict | None):
    if path == "/login":
        body, title = _login_body(None), "Log in"
    else:
        body, title = _signup_body(None), "Sign up"
    html_bytes = render_shell(title=title, user=user, active_path=path, body=body)
    return 200, _HTML_HEADERS, html_bytes


# ---------------------------------------------------------------------------
# authed-only pages: /, /split, /requests, /authorizations
# ---------------------------------------------------------------------------

def _home_body() -> str:
    return """<section class="placeholder-card">
  <h1>Welcome back</h1>
  <p class="muted">Your balance, pay and request tools are coming soon.</p>
</section>"""


def _split_body() -> str:
    return """<section class="placeholder-card">
  <h1>Split a bill</h1>
  <p class="muted">Splitting a bill between several people is coming soon.</p>
</section>"""


def _requests_body(user: dict) -> str:
    uid = user["id"]
    has_any = any(r["requester_id"] == uid or r["payer_id"] == uid for r in STORE.requests.values())
    if not has_any:
        return """<section class="placeholder-card">
  <h1>Requests</h1>
  <p data-testid="empty-requests" class="empty-state">No requests yet.</p>
</section>"""
    return """<section class="placeholder-card">
  <h1>Requests</h1>
  <p class="muted">Your incoming and outgoing requests are coming soon.</p>
</section>"""


def _authorizations_body(user: dict) -> str:
    uid = user["id"]
    has_any = any(a["from_user_id"] == uid or a["to_user_id"] == uid for a in STORE.authorizations.values())
    if not has_any:
        return """<section class="placeholder-card">
  <h1>Authorizations</h1>
  <p data-testid="empty-authorizations" class="empty-state">No authorizations yet.</p>
</section>"""
    return """<section class="placeholder-card">
  <h1>Authorizations</h1>
  <p class="muted">Your holds are coming soon.</p>
</section>"""


_AUTHED_PAGE_BODY = {
    "/": lambda user: (_home_body(), "Home"),
    "/split": lambda user: (_split_body(), "Split"),
    "/requests": lambda user: (_requests_body(user), "Requests"),
    "/authorizations": lambda user: (_authorizations_body(user), "Authorizations"),
}


def render_authed_page(path: str, user: dict | None):
    if user is None:
        return _redirect("/login")
    body, title = _AUTHED_PAGE_BODY[path](user)
    html_bytes = render_shell(title=title, user=user, active_path=path, body=body)
    return 200, _HTML_HEADERS, html_bytes


# ---------------------------------------------------------------------------
# form submissions: POST /login, /signup, /logout
# ---------------------------------------------------------------------------

def _handle_login(form: dict):
    email = form.get("email", "")
    password = form.get("password", "")
    user = STORE.users_by_email.get(email)
    # Same constant-time-against-an-unknown-email discipline as
    # /auth/login (R-1-086) — a wrong password and an unknown email must
    # cost the same, or wall-clock timing tells the two apart.
    hash_to_check = user["password_hash"] if user is not None else DUMMY_PASSWORD_HASH
    ok = verify_password(password, hash_to_check)
    if user is None or not ok:
        html_bytes = render_shell(title="Log in", user=None, active_path="/login",
                                   body=_login_body("Incorrect email or password."))
        return 200, _HTML_HEADERS, html_bytes
    token = secrets.token_urlsafe(32)
    STORE.tokens[token] = user["id"]
    return _redirect("/", set_cookie=_session_cookie(token))


def _validate_signup(email: str, password: str, display_name: str) -> str | None:
    if "@" not in email:
        return "Enter a valid email address."
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "Enter a valid email address."
    if email in STORE.users_by_email:
        return "That email is already registered."
    if len(password) < _MIN_PASSWORD_LEN:
        return f"Password must be at least {_MIN_PASSWORD_LEN} characters."
    if not display_name:
        return "Enter your name."
    return None


def _handle_signup(form: dict):
    email = form.get("email", "")
    password = form.get("password", "")
    display_name = form.get("display_name", "")
    error = _validate_signup(email, password, display_name)
    if error is None:
        handle = derive_handle(email)
        if handle in STORE.users_by_handle:
            error = "That email is already registered."
    if error is not None:
        html_bytes = render_shell(title="Sign up", user=None, active_path="/signup",
                                   body=_signup_body(error))
        return 200, _HTML_HEADERS, html_bytes

    handle = derive_handle(email)
    user_id = secrets.token_urlsafe(16)
    user = {
        "id": user_id, "email": email, "password_hash": hash_password(password),
        "display_name": display_name, "handle": handle, "balance": 0,
    }
    STORE.users_by_id[user_id] = user
    STORE.users_by_handle[handle] = user_id
    STORE.users_by_email[email] = user
    STORE.wallets[user_id] = 0

    token = secrets.token_urlsafe(32)
    STORE.tokens[token] = user_id
    return _redirect("/", set_cookie=_session_cookie(token))


def _handle_logout(cookies: dict):
    token = cookies.get("pocketful_session")
    if token:
        STORE.tokens.pop(token, None)
    return _redirect("/login", set_cookie=_clear_session_cookie())


def handle_post(path: str, form: dict, cookies: dict):
    if path == "/login":
        return _handle_login(form)
    if path == "/signup":
        return _handle_signup(form)
    return _handle_logout(cookies)
