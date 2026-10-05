"""The one page shell every route renders through (R-2-093: navigation
consistent across every required route) plus the amount formatter shared
with the JSON-free pages (R-2-100). Nothing here is version-specific to
what any page puts in its `body` — that stays in `pages.py`.
"""
from __future__ import annotations

import html
import json

NAV_LINKS = [
    ("/", "Home"),
    ("/requests", "Requests"),
    ("/split", "Split"),
    ("/authorizations", "Authorizations"),
    ("/statement", "Statement"),
]

# One inline mark, bundled in the page itself (R-U-008: no icon/font CDN).
# Used both as the header brand and, in monochrome, for each bottom-tab
# icon and every empty-state illustration below.
_BRAND_MARK_SVG = (
    '<svg class="brand-mark" width="22" height="22" viewBox="0 0 24 24" '
    'fill="none" aria-hidden="true" focusable="false">'
    '<rect x="2" y="6" width="20" height="14" rx="3" fill="currentColor"/>'
    '<rect x="2" y="6" width="20" height="4" rx="2" fill="currentColor" opacity="0.55"/>'
    '<circle cx="17" cy="14" r="2.2" fill="var(--color-surface)"/>'
    '</svg>'
)

_NAV_ICON_SVG = {
    "/": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true" focusable="false">'
         '<path d="M4 11.5 12 5l8 6.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
         '<path d="M6 10v9h12v-9" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>',
    "/requests": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true" focusable="false">'
                 '<path d="M12 4v16M4 12h16" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    "/split": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true" focusable="false">'
              '<circle cx="8" cy="8" r="3" stroke="currentColor" stroke-width="2"/>'
              '<circle cx="16" cy="16" r="3" stroke="currentColor" stroke-width="2"/>'
              '<path d="M10.2 9.8 13.8 14.2" stroke="currentColor" stroke-width="2"/></svg>',
    "/authorizations": '<svg viewBox="0 0 24 24" width="20" height="20" fill="none" aria-hidden="true" focusable="false">'
                        '<rect x="5" y="10" width="14" height="10" rx="2" stroke="currentColor" stroke-width="2"/>'
                        '<path d="M8 10V7a4 4 0 0 1 8 0v3" stroke="currentColor" stroke-width="2"/></svg>',
}


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def format_amount(amount: int, currency: str, minor_units: int) -> str:
    """R-2-100: exactly `minor_units` decimal places, a single space, then
    the currency code; no decimal point at all when `minor_units` is 0.
    Balances are never negative (R-1-002), so no sign is ever shown."""
    if minor_units == 0:
        return f"{amount} {currency}"
    digits = str(amount).rjust(minor_units + 1, "0")
    whole, frac = digits[:-minor_units], digits[-minor_units:]
    return f"{whole}.{frac} {currency}"


def _nav_html(active_path: str) -> str:
    links = []
    for path, label in NAV_LINKS:
        cls = "nav-link nav-link-active" if path == active_path else "nav-link"
        current = ' aria-current="page"' if path == active_path else ""
        links.append(f'<a class="{cls}" href="{path}"{current}>{esc(label)}</a>')
    return "".join(links)


def _bottom_tab_html(active_path: str) -> str:
    """R-U-016: a 375 px bottom tab bar. This is an ADDITIONAL navigation
    surface, not a replacement for the top nav's links (R-U-005) -- both
    point at the same routes, the top row is just hidden under 480px via
    CSS in favour of this one, and nothing a frozen suite fills or clicks
    lives in either nav, so hiding one here is pure chrome, not a gated
    form field."""
    tabs = []
    for path, label in NAV_LINKS:
        cls = "tab-link tab-link-active" if path == active_path else "tab-link"
        current = ' aria-current="page"' if path == active_path else ""
        icon = _NAV_ICON_SVG.get(path, "")
        tabs.append(f'<a class="{cls}" href="{path}"{current}>{icon}<span class="tab-label">{esc(label)}</span></a>')
    return f'<nav class="bottom-tab-bar" aria-label="Primary">{"".join(tabs)}</nav>'


def empty_state_html(testid: str, sentence: str, *, cta_label: str | None = None,
                      cta_href: str | None = None) -> str:
    """R-U-017: every empty list gets an icon, one sentence and a call to
    action -- the same `data-testid` every frozen suite already locates
    by (`.count() > 0` only, never exact text, so the sentence and CTA
    are free to change)."""
    cta_html = ""
    if cta_label and cta_href:
        cta_html = f'<a class="btn btn-ghost empty-state-cta" href="{esc(cta_href)}">{esc(cta_label)}</a>'
    return (f'<div data-testid="{esc(testid)}" class="empty-state">'
            f'<div class="empty-state-icon" aria-hidden="true">{_BRAND_MARK_SVG}</div>'
            f'<p class="empty-state-text">{esc(sentence)}</p>{cta_html}</div>')


def _user_chip_html(user: dict | None) -> str:
    if user is None:
        return ""
    # R-2-123/124: current-user and current-handle are siblings, each
    # holding only its own text — a prefix, "@" or label belongs beside
    # them, never inside, or "text is exactly the handle" breaks.
    return f"""<div class="user-chip">
      <span data-testid="current-user">{esc(user["display_name"])}</span>
      <span class="handle-prefix">@<span data-testid="current-handle">{esc(user["handle"])}</span></span>
      <form method="POST" action="/logout" class="logout-form">
        <button type="submit" data-testid="logout-button" class="btn btn-ghost">Log out</button>
      </form>
    </div>"""


def _session_script_html(session: dict | None) -> str:
    """Embeds the caller's own bearer token (the exact value the session
    cookie already carries, HttpOnly, never readable by JS) into the page
    itself, so the client-side fetch layer can attach the ordinary
    `Authorization: Bearer ...` header a JSON caller would — R-2-154's
    sequencing and R-2-157's uncertain-retry both need real `fetch()`
    calls, and they must authenticate the exact way the JSON API already
    does (never via the cookie: R-1-089 is about the cookie, not about a
    page revealing its own session to its own script)."""
    if session is None:
        return ""
    # JSON can contain "</script>"; escaping the slash keeps this inert
    # even though every value here is server-controlled, not user text.
    payload = json.dumps(session).replace("</", "<\\/")
    return f'<script id="pocketful-session" type="application/json">{payload}</script>'


def render_shell(*, title: str, user: dict | None, active_path: str, body: str,
                  session: dict | None = None) -> bytes:
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Pocketful</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<header class="app-header">
  <a class="brand" href="/">{_BRAND_MARK_SVG}<span class="brand-name">Pocketful</span></a>
  <nav class="main-nav">{_nav_html(active_path)}</nav>
  {_user_chip_html(user)}
</header>
<main class="app-main">
{body}
</main>
{_bottom_tab_html(active_path)}
{_session_script_html(session)}
<script src="/static/app.js"></script>
</body>
</html>"""
    return page.encode("utf-8")
