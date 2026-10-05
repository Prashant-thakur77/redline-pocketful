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

from datetime import datetime, timezone

from ..routes.activity import ActivityEndpoint
from ..routes.me import MeEndpoint
from ..store import STORE
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
    # R-U-012: amount first (large type), then recipient, then note. Every
    # field keeps its existing data-testid/name — only the layout order of
    # the *same* elements changes, so a locator-by-testid test is unaffected.
    return f"""<section class="form-card primary-panel" id="pay-form" data-panel="pay">
  <h2>Pay</h2>
  <form data-testid="pay-form" data-state="idle" class="form form-amount-first" novalidate>
    {_field("Amount", "pay-amount", name="amount")}
    {_field("To (handle)", "pay-handle", name="handle")}
    {_field("Note", "pay-note", name="note", required=False)}
    <label class="field">
      <span class="field-label">Visibility</span>
      <select name="visibility" data-testid="pay-visibility">
        <option value="public">Public</option>
        <option value="private">Private</option>
      </select>
    </label>
    <div data-testid="pay-review" class="form-review" aria-live="polite" hidden></div>
    <button type="submit" data-testid="pay-submit" class="btn btn-primary">Pay</button>
  </form>
  <div data-testid="pay-error-slot" class="form-slot"></div>
</section>"""


def _request_form_html() -> str:
    return f"""<section class="form-card secondary-panel" data-panel="request">
  <h2>Request</h2>
  <form data-testid="request-form" data-state="idle" class="form form-amount-first" novalidate>
    {_field("Amount", "request-amount", name="amount")}
    {_field("From (handle)", "request-handle", name="handle")}
    {_field("Note", "request-note", name="note", required=False)}
    <div data-testid="request-review" class="form-review" aria-live="polite" hidden></div>
    <button type="submit" data-testid="request-submit" class="btn btn-primary">Request</button>
  </form>
  <div data-testid="request-error-slot" class="form-slot"></div>
</section>"""


def _primary_action_html() -> str:
    # R-U-012: one PRIMARY action (Pay, by default) with a toggle to swap
    # which of Pay/Request is visually emphasised. Both forms, and every
    # field inside them, stay rendered and reachable at all times (R-U-005
    # forbids gating an existing element behind a click/display:none) --
    # the toggle only swaps which `.form-card` carries the `primary-panel`
    # styling (bigger card, prominent button) via the wrapper's
    # `data-active` attribute; no element is ever removed or display:none'd.
    return f"""<div class="primary-action" data-active="pay">
  <div class="primary-toggle" role="tablist" aria-label="Choose an action">
    <button type="button" data-testid="primary-toggle-pay" class="toggle-btn toggle-btn-active"
            role="tab" aria-selected="true" data-target="pay">Pay</button>
    <button type="button" data-testid="primary-toggle-request" class="toggle-btn"
            role="tab" aria-selected="false" data-target="request">Request</button>
  </div>
  {_pay_form_html()}
  {_request_form_html()}
</div>"""


def _authorize_form_html() -> str:
    # R-U-013: a secondary action, its own panel -- always reachable, never
    # behind the Pay/Request toggle above.
    return f"""<section class="form-card secondary-panel" data-panel="authorize">
  <h2>Authorize a hold</h2>
  <form data-testid="authorize-form" data-state="idle" class="form form-amount-first" novalidate>
    {_field("Amount", "authorize-amount", name="amount")}
    {_field("To (handle)", "authorize-handle", name="handle")}
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


def _initials(handle: str | None) -> str:
    return esc((handle or "?")[:2].upper())


def _relative_time(created_at: str) -> str:
    try:
        then = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return ""
    delta = datetime.now(timezone.utc) - then
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _day_label(created_at: str) -> str:
    try:
        then = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return "Earlier"
    today = datetime.now(timezone.utc).date()
    then_date = then.astimezone(timezone.utc).date()
    if then_date == today:
        return "Today"
    if (today - then_date).days == 1:
        return "Yesterday"
    return then_date.isoformat()


def _activity_item_html(p: dict, minor_units: int, me_user_id: str) -> str:
    """R-U-015: the human-readable summary line, avatar initials and
    in/out direction are ALL additional elements alongside the existing
    `activity-parties-{id}`/`activity-amount-{id}`/`activity-note-{id}`
    (R-U-011) -- those three keep their exact current text untouched; the
    sign/colour live in a sibling span, never inside `activity-amount-{id}`
    itself, since that element's text is `"<decimal> <CODE>"` exactly."""
    pid = p["payment_id"]
    amount_fmt = esc(format_amount(p["amount"], p["currency"], minor_units))
    from_h, to_h = p.get("from_handle") or "?", p.get("to_handle") or "?"
    is_outgoing = p["from_user_id"] == me_user_id
    direction_cls = "activity-direction-out" if is_outgoing else "activity-direction-in"
    direction_sign = "−" if is_outgoing else "+"
    verb = "You paid" if is_outgoing else f"{esc(from_h)} paid you" if p["to_user_id"] == me_user_id else f"{esc(from_h)} paid"
    counterpart = esc(to_h) if is_outgoing else ""
    summary = f"{verb} {counterpart}".strip()
    note = p["note"]
    if note:
        summary += f" · {esc(note)}"
    summary += f" · {esc(_relative_time(p['created_at']))}"
    return f"""<article data-testid="activity-item-{esc(pid)}" data-visibility="{esc(p["visibility"])}"
         class="activity-item">
  <div class="activity-avatar" aria-hidden="true">{_initials(to_h if is_outgoing else from_h)}</div>
  <div class="activity-body">
    <p class="activity-summary">{summary}</p>
    <p data-testid="activity-parties-{esc(pid)}" class="activity-parties">{esc(from_h)} &rarr; {esc(to_h)}</p>
    <p data-testid="activity-note-{esc(pid)}" class="activity-note">{esc(note)}</p>
  </div>
  <p class="activity-amount-wrap">
    <span class="activity-direction {direction_cls}" aria-hidden="true">{direction_sign}</span>
    <span data-testid="activity-amount-{esc(pid)}" class="activity-amount">{amount_fmt}</span>
  </p>
  <a data-testid="payment-detail-link-{esc(pid)}" class="activity-detail-link" href="/payments/{esc(pid)}">Details</a>
</article>"""


def _activity_html(payments: list[dict], minor_units: int, me_user_id: str) -> str:
    if not payments:
        inner = empty_state_html("empty-activity", "No activity yet.",
                                  cta_label="Send your first payment", cta_href="#pay-form")
    else:
        # R-2-132: already newest-first (ActivityEndpoint sorts by seq
        # descending) — rendered in the order given, never re-sorted here.
        # R-U-015 day headers are flat siblings alongside each
        # `activity-item-{id}` inside `activity-list`, never wrapping it,
        # so a frozen test walking `activity-list > *` for item ids by
        # data-testid still finds every item at its original relative
        # position (headers simply don't match that attribute).
        parts = []
        last_day = None
        for p in payments:
            day = _day_label(p["created_at"])
            if day != last_day:
                parts.append(f'<p class="activity-day-header">{esc(day)}</p>')
                last_day = day
            parts.append(_activity_item_html(p, minor_units, me_user_id))
        inner = f'<div data-testid="activity-list">{"".join(parts)}</div>'
    return f"""<section class="activity-card" data-testid="activity-host" aria-label="Activity">
  <h2>Activity</h2>
  <div class="activity-mount">{inner}</div>
</section>"""


def render_home_body(token: str) -> str:
    _, me = _call_authed(_ME_ENDPOINT, "GET", "/me", token)
    _, activity = _call_authed(_ACTIVITY_ENDPOINT, "GET", "/activity", token, query={"limit": "50"})
    # R-U-039: the entry point to the operator-only batch screen is simply
    # absent for anyone else -- read straight from STORE, never a GET /me
    # field (R-U-001 forbids adding one).
    operator_link = ""
    if me["user_id"] in STORE.settlement_operator_ids:
        operator_link = '<a href="/correction-batches" class="btn btn-ghost">Correction batches</a>'
    return "".join([
        _wallet_html(me),
        '<div class="forms-grid">', _primary_action_html(), _authorize_form_html(), "</div>",
        operator_link,
        _activity_html(activity["payments"], me["minor_units"], me["user_id"]),
    ])


def session_payload(user: dict, token: str) -> dict:
    """What the client-side fetch layer needs to authenticate exactly like
    a JSON caller (R-1-089: this is the page revealing its own session to
    its own script, never the cookie authenticating anything) and to
    format amounts identically to the server (R-2-100)."""
    _, me = _call_authed(_ME_ENDPOINT, "GET", "/me", token)
    return {"token": token, "user_id": user["id"], "currency": me["currency"], "minor_units": me["minor_units"]}
