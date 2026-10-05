"""The `/statement` screen — R-U-030..033.

Negotiated with the existing JSON `GET /statement` (R-U-041): this module
is reached ONLY when `Accept: text/html` wins (`ui/__init__.py`); every
other caller still gets `StatementEndpoint`'s byte-identical JSON. The
server-side render below is the DEFAULT window only (no `from`/`to`/
`as_of`/`known_at`/`snapshot` in the URL) -- once the page is interactive,
`static/app.js` drives every subsequent apply/page/as-of lookup through
the exact same `GET /statement`/`GET /me` endpoints (R-U-002), never a
second implementation of the window/snapshot rules already in
`statement.py`/`me.py`.
"""
from __future__ import annotations

from ..routes.me import MeEndpoint
from ..routes.statement import StatementEndpoint
from .calls import call_authed
from .layout import empty_state_html, esc, format_amount

_STATEMENT_ENDPOINT = StatementEndpoint()
_ME_ENDPOINT = MeEndpoint()


def _entry_html(entry: dict, currency: str, minor_units: int) -> str:
    pid = entry["payment_id"]
    amount_fmt = esc(format_amount(entry["amount"], currency, minor_units))
    balance_fmt = esc(format_amount(entry["balance_after"], currency, minor_units))
    return f"""<article data-testid="statement-entry-{esc(pid)}" class="list-item">
  <p class="list-item-parties">{esc(entry["effective_at"])}</p>
  <p data-testid="statement-entry-amount-{esc(pid)}" class="list-item-amount">{amount_fmt}</p>
  <p data-testid="statement-entry-balance-{esc(pid)}" class="list-item-amount">{balance_fmt}</p>
  <p data-testid="statement-entry-revision-{esc(pid)}" class="list-item-note">rev {entry["revision"]}</p>
</article>"""


def render_statement_body(user: dict, token: str) -> str:
    status, body = call_authed(_STATEMENT_ENDPOINT, "GET", "/statement", token, query={"limit": "50"})
    _, me = call_authed(_ME_ENDPOINT, "GET", "/me", token)
    currency, minor_units = me["currency"], me["minor_units"]
    entries = body["entries"]
    if entries:
        list_inner = "".join(_entry_html(e, currency, minor_units) for e in entries)
    else:
        list_inner = empty_state_html("empty-statement", "No entries in this window.")
    opening_fmt = esc(format_amount(body["opening_balance"], currency, minor_units))
    closing_fmt = esc(format_amount(body["closing_balance"], currency, minor_units))
    return f"""<section class="placeholder-card" id="statement-screen"
         data-snapshot="{esc(body["snapshot"])}" data-offset="0" data-limit="50"
         data-currency="{esc(currency)}" data-minor-units="{minor_units}">
  <h1>Statement</h1>
  <form data-testid="statement-form" class="form form-inline" novalidate>
    <label class="field">
      <span class="field-label">From</span>
      <input type="date" data-testid="statement-from">
    </label>
    <label class="field">
      <span class="field-label">To</span>
      <input type="date" data-testid="statement-to">
    </label>
    <label class="field">
      <span class="field-label">As of</span>
      <input type="date" data-testid="statement-as-of">
    </label>
    <label class="field">
      <span class="field-label">Known at</span>
      <input type="date" data-testid="statement-known-at">
    </label>
    <button type="button" data-testid="statement-apply" class="btn btn-primary">Apply</button>
  </form>
  <div data-testid="statement-error" class="form-slot" hidden></div>
  <div data-testid="statement-loading" class="form-slot" hidden>Loading…</div>
  <p class="wallet-line"><span class="wallet-label">As of balance</span>
    <span data-testid="as-of-balance" class="wallet-amount"></span></p>
  <p class="wallet-line"><span class="wallet-label">Opening</span>
    <span data-testid="statement-opening-balance" class="wallet-amount">{opening_fmt}</span></p>
  <p class="wallet-line"><span class="wallet-label">Closing</span>
    <span data-testid="statement-closing-balance" class="wallet-amount">{closing_fmt}</span></p>
  <p data-testid="statement-snapshot-note" class="list-item-note" hidden></p>
  <div data-testid="statement-list" class="list">{list_inner}</div>
  <div class="list-item-actions">
    <button type="button" data-testid="statement-prev" class="btn btn-ghost">Previous</button>
    <button type="button" data-testid="statement-next" class="btn btn-ghost">Next</button>
  </div>
</section>"""
