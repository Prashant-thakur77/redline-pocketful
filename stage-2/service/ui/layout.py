"""The one page shell every route renders through (R-2-093: navigation
consistent across every required route) plus the amount formatter shared
with the JSON-free pages (R-2-100). Nothing here is version-specific to
what any page puts in its `body` — that stays in `pages.py`.
"""
from __future__ import annotations

import html

NAV_LINKS = [
    ("/", "Home"),
    ("/requests", "Requests"),
    ("/split", "Split"),
    ("/authorizations", "Authorizations"),
]


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
        links.append(f'<a class="{cls}" href="{path}">{esc(label)}</a>')
    return "".join(links)


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


def render_shell(*, title: str, user: dict | None, active_path: str, body: str) -> bytes:
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
  <a class="brand" href="/">Pocketful</a>
  <nav class="main-nav">{_nav_html(active_path)}</nav>
  {_user_chip_html(user)}
</header>
<main class="app-main">
{body}
</main>
<script src="/static/app.js"></script>
</body>
</html>"""
    return page.encode("utf-8")
