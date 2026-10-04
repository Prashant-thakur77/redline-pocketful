"""The browser shell — R-2-090..093, R-2-120..125.

A deliberately separate code path from `pipeline.py`/`server.py`'s JSON
router: `try_handle` is consulted first and, when it returns a result, the
request never reaches `ROUTER.match` at all. That split is what makes
R-2-091 safe to implement — the JSON behaviour of `/requests` and
`/authorizations` for every existing API test is simply never touched by
anything in this package; only a GET carrying `Accept: text/html` (and
only on the six routes named in R-2-090) is ever diverted here.

Session transport (decided once, used everywhere): a single HttpOnly
cookie whose value *is* the same bearer token `/auth/login` issues. That
keeps "signed in" identical on both sides without a second user table,
and `auth.authenticate()` (the JSON pipeline's only auth entry point)
never reads cookies — so a cookie can never authenticate a JSON request,
per R-1-089.
"""
from __future__ import annotations

from urllib.parse import parse_qsl

from ..store import STORE
from . import pages

SESSION_COOKIE = "pocketful_session"

# R-2-090: the six required routes. "/signup"/"/login" need no session;
# "/"/"/split" are UI-only and always require one; "/requests"/
# "/authorizations" are shared with the JSON API and only divert here on
# an explicit text/html Accept (R-2-091).
_PUBLIC_PAGES = {"/signup", "/login"}
_AUTHED_ONLY_PAGES = {"/", "/split"}
_NEGOTIATED_PAGES = {"/requests", "/authorizations"}
_POST_PAGES = {"/login", "/signup", "/logout"}


def _parse_accept(accept: str) -> list[tuple[str, float]]:
    entries = []
    for part in accept.split(","):
        part = part.strip()
        if not part:
            continue
        pieces = part.split(";")
        media_type = pieces[0].strip().lower()
        q = 1.0
        for param in pieces[1:]:
            param = param.strip()
            if param.startswith("q="):
                try:
                    q = float(param[2:])
                except ValueError:
                    q = 1.0
        entries.append((media_type, q))
    return entries


def _wants_html(headers: dict) -> bool:
    """R-2-091: a real Accept parse, not a substring search — a naive
    `"text/html" in accept` both matches values that merely contain the
    substring without being the media type at all (`text/htmlx`,
    `application/text/html`) and ignores q-values entirely, wrongly
    diverting a client that lists `text/html` only as a near-zero-
    priority fallback behind `application/json` (adversary's second
    N2-5 breach). The exact token `text/html` must be present with a
    q-value at least as high as every other listed type's; curl's
    default `*/*`, a bare missing header, and an explicit
    `application/json` must all still mean JSON."""
    accept = headers.get("accept", "")
    if not accept:
        return False
    html_q = None
    best_other_q = 0.0
    for media_type, q in _parse_accept(accept):
        if media_type == "text/html":
            html_q = q if html_q is None else max(html_q, q)
        else:
            best_other_q = max(best_other_q, q)
    if html_q is None or html_q <= 0:
        return False
    return html_q >= best_other_q


def _parse_cookies(headers: dict) -> dict:
    raw = headers.get("cookie", "")
    out: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        out[key.strip()] = value.strip()
    return out


def _user_for_token(token: str | None) -> dict | None:
    if not token:
        return None
    user_id = STORE.tokens.get(token)
    if user_id is None:
        return None
    return STORE.users_by_id.get(user_id)


def current_user(headers: dict) -> dict | None:
    """Cookie first (the real browser-navigation case — a `page.goto` never
    carries an `Authorization` header), falling back to a bearer token for
    the negotiated paths: R-2-091's own test drives `/requests` with
    `Accept: text/html` *and* `Authorization: Bearer ...` directly, as an
    API client would, with no cookie at all."""
    user = _user_for_token(_parse_cookies(headers).get(SESSION_COOKIE))
    if user is not None:
        return user
    auth_header = headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return _user_for_token(auth_header[len("Bearer "):])
    return None


def try_handle(method: str, path: str, headers: dict, raw_body: bytes, query: dict):
    """Returns `(status, header_pairs, body_bytes)` when this request is a
    UI concern this module owns; `None` when the caller should fall
    through to the ordinary JSON router untouched."""
    if path.startswith("/static/"):
        return pages.serve_static(path) if method == "GET" else None

    if method == "GET":
        if path in _PUBLIC_PAGES:
            return pages.render_public_page(path, current_user(headers))
        if path in _AUTHED_ONLY_PAGES or (path in _NEGOTIATED_PAGES and _wants_html(headers)):
            return pages.render_authed_page(path, current_user(headers))
        return None

    if method == "POST" and path in _POST_PAGES:
        form = dict(parse_qsl(raw_body.decode("utf-8", "replace")))
        return pages.handle_post(path, form, _parse_cookies(headers))

    return None
