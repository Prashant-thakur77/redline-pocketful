"""The `/` screen: wallet numbers, the pay/request/authorize forms, and the
activity feed — R-2-100, R-2-103..111, R-2-126..132, R-2-139..141,
R-2-150..160.

Every number shown here is read through the exact endpoint object the
JSON API uses (`MeEndpoint`, `ActivityEndpoint`), the same discipline
R-2-185 states for writes — this module never re-derives `held`/
`available` or re-filters the activity feed itself. The pay/request/
authorize forms are plain HTML (R-2-150's "keep values after success"
and R-2-151/157's idempotent-resubmit/uncertain-retry behaviours all
need the fields to survive a non-reloading submit, which only a
client-side `fetch()` gives) — the form markup here only has to be
*reachable*; `static/app.js` drives the actual submit.
"""
from __future__ import annotations

from ..routes.activity import ActivityEndpoint
from ..routes.me import MeEndpoint
from .calls import call_authed as _call_authed
from .layout import empty_state_html, esc, format_amount

_ME_ENDPOINT = MeEndpoint()
_ACTIVITY_ENDPOINT = ActivityEndpoint()


def _wallet_html(me: dict) -> str:
    """R-U-010: Available is the headline figure, with labelled Total and
    On-hold lines beneath it. The label spans are ADDITIONAL elements
    beside each testid'd amount (R-U-011) -- `wallet-balance`/
    `wallet-available`/`wallet-held` keep their existing `data-testid`,
    exact `"<decimal> <CODE>"` text and `data-amount` attribute
    untouched; only the DOM order and the added labels change. Held
    stays conditional on being present at all (R-2-xxx: absent, not
    zeroed, when there is nothing on hold)."""
    currency, minor_units = me["currency"], me["minor_units"]
    balance_fmt = esc(format_amount(me["total"], currency, minor_units))
    available_fmt = esc(format_amount(me["available"], currency, minor_units))
    held_html = ""
    if me["held"] > 0:
        held_fmt = esc(format_amount(me["held"], currency, minor_units))
        held_html = (f'<p class="wallet-line"><span class="wallet-label">On hold</span>'
                      f'<span data-testid="wallet-held" data-amount="{me["held"]}" '
                      f'class="wallet-amount wallet-held">{held_fmt}</span></p>')
    return f"""<section class="wallet-card" aria-label="Wallet">
  <h1>Wallet</h1>
  <p class="wallet-line-primary">
    <span class="wallet-label">Available</span>
    <span data-testid="wallet-available" data-amount="{me["available"]}"
       class="wallet-amount wallet-available">{available_fmt}</span>
  </p>
  <p class="wallet-line">
    <span class="wallet-label">Total</span>
    <span data-testid="wallet-balance" data-amount="{me["total"]}" class="wallet-amount wallet-balance">{balance_fmt}</span>
  </p>
  {held_html}
  <button type="button" data-testid="wallet-refresh" class="btn btn-ghost">Refresh</button>
</section>"""


def _field(label: str, testid: str, *, name: str, type_: str = "text", required: bool = True) -> str:
    req = " required" if required else ""
    return f"""<label class="field">
      <span class="field-label">{esc(label)}</span>
      <input type="{type_}" name="{name}" data-testid="{testid}"{req}>
    </label>"""


def _pay_form_html() -> str:
    return f"""<section class="form-card" id="pay-form">
  <h2>Pay</h2>
  <form data-testid="pay-form" data-state="idle" class="form" novalidate>
    {_field("To (handle)", "pay-handle", name="handle")}
    {_field("Amount", "pay-amount", name="amount")}
    {_field("Note", "pay-note", name="note", required=False)}
    <label class="field">
      <span class="field-label">Visibility</span>
      <select name="visibility" data-testid="pay-visibility">
        <option value="public">Public</option>
        <option value="private">Private</option>
      </select>
    </label>
    <button type="submit" data-testid="pay-submit" class="btn btn-primary">Pay</button>
  </form>
  <div data-testid="pay-error-slot" class="form-slot"></div>
</section>"""


def _request_form_html() -> str:
    return f"""<section class="form-card">
  <h2>Request</h2>
  <form data-testid="request-form" data-state="idle" class="form" novalidate>
    {_field("From (handle)", "request-handle", name="handle")}
    {_field("Amount", "request-amount", name="amount")}
    {_field("Note", "request-note", name="note", required=False)}
    <button type="submit" data-testid="request-submit" class="btn btn-primary">Request</button>
  </form>
  <div data-testid="request-error-slot" class="form-slot"></div>
</section>"""


def _authorize_form_html() -> str:
    return f"""<section class="form-card">
  <h2>Authorize a hold</h2>
  <form data-testid="authorize-form" data-state="idle" class="form" novalidate>
    {_field("To (handle)", "authorize-handle", name="handle")}
    {_field("Amount", "authorize-amount", name="amount")}
    {_field("Note", "authorize-note", name="note", required=False)}
    <label class="field">
      <span class="field-label">Visibility</span>
      <select name="visibility" data-testid="authorize-visibility">
        <option value="public">Public</option>
        <option value="private">Private</option>
      </select>
    </label>
    <button type="submit" data-testid="authorize-submit" class="btn btn-primary">Authorize</button>
  </form>
  <div data-testid="authorize-error-slot" class="form-slot"></div>
</section>"""


def _activity_item_html(p: dict, minor_units: int) -> str:
    pid = p["payment_id"]
    amount_fmt = esc(format_amount(p["amount"], p["currency"], minor_units))
    from_h, to_h = p.get("from_handle") or "?", p.get("to_handle") or "?"
    return f"""<article data-testid="activity-item-{esc(pid)}" data-visibility="{esc(p["visibility"])}"
         class="activity-item">
  <p data-testid="activity-parties-{esc(pid)}" class="activity-parties">{esc(from_h)} &rarr; {esc(to_h)}</p>
  <p data-testid="activity-amount-{esc(pid)}" class="activity-amount">{amount_fmt}</p>
  <p data-testid="activity-note-{esc(pid)}" class="activity-note">{esc(p["note"])}</p>
</article>"""


def _activity_html(payments: list[dict], minor_units: int) -> str:
    if not payments:
        inner = empty_state_html("empty-activity", "No activity yet.",
                                  cta_label="Send your first payment", cta_href="#pay-form")
    else:
        # R-2-132: already newest-first (ActivityEndpoint sorts by seq
        # descending) — rendered in the order given, never re-sorted here.
        items = "".join(_activity_item_html(p, minor_units) for p in payments)
        inner = f'<div data-testid="activity-list">{items}</div>'
    return f"""<section class="activity-card" data-testid="activity-host" aria-label="Activity">
  <h2>Activity</h2>
  <div class="activity-mount">{inner}</div>
</section>"""


def render_home_body(token: str) -> str:
    _, me = _call_authed(_ME_ENDPOINT, "GET", "/me", token)
    _, activity = _call_authed(_ACTIVITY_ENDPOINT, "GET", "/activity", token, query={"limit": "50"})
    return "".join([
        _wallet_html(me),
        '<div class="forms-grid">', _pay_form_html(), _request_form_html(), _authorize_form_html(), "</div>",
        _activity_html(activity["payments"], me["minor_units"]),
    ])


def session_payload(user: dict, token: str) -> dict:
    """What the client-side fetch layer needs to authenticate exactly like
    a JSON caller (R-1-089: this is the page revealing its own session to
    its own script, never the cookie authenticating anything) and to
    format amounts identically to the server (R-2-100)."""
    _, me = _call_authed(_ME_ENDPOINT, "GET", "/me", token)
    return {"token": token, "user_id": user["id"], "currency": me["currency"], "minor_units": me["minor_units"]}
