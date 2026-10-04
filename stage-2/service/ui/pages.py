"""Page bodies and form handlers for the six required routes (R-2-090) plus
signup/login/logout (R-2-120..125). `/` and `/split` ship chrome and a
considered empty state only — their real content is N2-6/N2-7's scope;
`/requests` and `/authorizations` here likewise render chrome plus an
honest empty-or-not-yet-built state, never a stored `held`/`available`
number, since neither screen's real listing exists yet.
"""
from __future__ import annotations

from ..errors import ApiError
from ..json_utils import dumps
from ..pipeline import RequestCtx
from ..routes.auth import LoginEndpoint, SignupEndpoint
from ..store import STORE
from . import assets
from .layout import esc, render_shell

_HTML_HEADERS = [("Content-Type", "text/html; charset=utf-8")]

# R-2-185: no UI handler reimplements a write the JSON API already has —
# the login/signup forms call these exact endpoint objects (translating
# form encoding in, and the response into a redirect or a rendered
# error), never touching STORE directly. One implementation means every
# guarantee the JSON path states (R-1-086/R-1-088) holds identically for
# the form path, by construction, not by a second copy staying in sync.
_LOGIN_ENDPOINT = LoginEndpoint()
_SIGNUP_ENDPOINT = SignupEndpoint()


def _call_endpoint(endpoint, path: str, fields: dict):
    ctx = RequestCtx(method="POST", path=path, raw_body=dumps(fields), headers={}, query={}, path_params={})
    return endpoint.handle(ctx)


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
    return f'<p class="form-error" data-testid="auth-error" data-state="error">{esc(message)}</p>'


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
    # No wallet/pay/activity content exists in this item yet (N2-6's
    # scope) — this really is an empty view, not a stand-in for one.
    return """<section class="placeholder-card" data-state="empty">
  <h1>Welcome back</h1>
  <p class="muted">Your balance, pay and request tools are coming soon.</p>
</section>"""


def _split_body() -> str:
    return """<section class="placeholder-card" data-state="empty">
  <h1>Split a bill</h1>
  <p class="muted">Splitting a bill between several people is coming soon.</p>
</section>"""


def _requests_body(user: dict) -> str:
    uid = user["id"]
    has_any = any(r["requester_id"] == uid or r["payer_id"] == uid for r in STORE.requests.values())
    if not has_any:
        return """<section class="placeholder-card" data-state="empty">
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
        return """<section class="placeholder-card" data-state="empty">
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
    try:
        status, body = _call_endpoint(_LOGIN_ENDPOINT, "/auth/login",
                                       {"email": form.get("email", ""), "password": form.get("password", "")})
    except ApiError:
        # Every failure path LoginEndpoint has is the one R-1-086 case —
        # unknown email and wrong password are indistinguishable, so the
        # form shows the same message regardless of which one it was.
        html_bytes = render_shell(title="Log in", user=None, active_path="/login",
                                   body=_login_body("Incorrect email or password."))
        return 200, _HTML_HEADERS, html_bytes
    return _redirect("/", set_cookie=_session_cookie(body["token"]))


def _handle_signup(form: dict):
    fields = {"email": form.get("email", ""), "password": form.get("password", ""),
              "display_name": form.get("display_name", "")}
    try:
        status, body = _call_endpoint(_SIGNUP_ENDPOINT, "/auth/signup", fields)
    except ApiError as exc:
        # SignupEndpoint's own messages (bad email shape, short password,
        # email/handle already taken) are already user-facing — shown
        # verbatim, the same validation a JSON caller would see.
        html_bytes = render_shell(title="Sign up", user=None, active_path="/signup",
                                   body=_signup_body(exc.message))
        return 200, _HTML_HEADERS, html_bytes
    return _redirect("/", set_cookie=_session_cookie(body["token"]))


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
