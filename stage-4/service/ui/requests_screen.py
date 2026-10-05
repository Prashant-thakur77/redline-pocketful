"""The `/requests` screen — R-2-133, R-2-134, R-2-156. SSR only; the
action buttons are bound and re-rendered by `static/app.js`'s request
handler, which calls the exact same `/requests/{id}/pay|decline|cancel`
routes (R-2-185).
"""
from __future__ import annotations

from ..routes.requests_read import RequestsListEndpoint
from ..store import STORE
from .calls import call_authed
from .layout import empty_state_html, esc, format_amount

_REQUESTS_LIST = RequestsListEndpoint()


def _actions_html(r: dict, user_id: str) -> str:
    if r["status"] != "pending":
        return ""
    actions = []
    if r["payer_id"] == user_id:
        actions.append(f'<button type="button" data-testid="request-pay-{esc(r["request_id"])}" '
                        f'data-action="pay" data-id="{esc(r["request_id"])}" class="btn btn-primary">Pay</button>')
        actions.append(f'<button type="button" data-testid="request-decline-{esc(r["request_id"])}" '
                        f'data-action="decline" data-id="{esc(r["request_id"])}" class="btn btn-ghost">Decline</button>')
    if r["requester_id"] == user_id:
        actions.append(f'<button type="button" data-testid="request-cancel-{esc(r["request_id"])}" '
                        f'data-action="cancel" data-id="{esc(r["request_id"])}" class="btn btn-ghost">Cancel</button>')
    return "".join(actions)


def _request_item_html(r: dict, user_id: str, minor_units: int) -> str:
    rid = r["request_id"]
    is_requester = r["requester_id"] == user_id
    counterpart = r["payer_handle"] if is_requester else r["requester_handle"]
    amount_fmt = esc(format_amount(r["amount"], r["currency"], minor_units))
    return f"""<article data-testid="request-item-{esc(rid)}" data-status="{esc(r["status"])}" class="list-item">
  <p class="list-item-parties">{esc(counterpart or "?")}</p>
  <p data-testid="request-amount-{esc(rid)}" class="list-item-amount">{amount_fmt}</p>
  <p class="list-item-note">{esc(r["note"])}</p>
  <div class="list-item-actions">{_actions_html(r, user_id)}</div>
</article>"""


def render_requests_body(user: dict, token: str) -> str:
    _, incoming_data = call_authed(_REQUESTS_LIST, "GET", "/requests", token,
                                    query={"direction": "incoming", "limit": "200"})
    _, outgoing_data = call_authed(_REQUESTS_LIST, "GET", "/requests", token,
                                    query={"direction": "outgoing", "limit": "200"})
    incoming, outgoing = incoming_data["requests"], outgoing_data["requests"]
    minor_units = STORE.minor_units
    # R-2-133: incoming-list/outgoing-list are always in the DOM — a user
    # with zero requests in both directions is an empty *state* of this
    # screen, not a different screen. Collapsing the whole page to a
    # placeholder when both are empty (the gate-3 finding) made the list
    # containers vanish along with the content, so any test navigating
    # straight to a route that happens to have no data for that user
    # timed out waiting for an element that genuinely never existed.
    empty_marker = ""
    if not incoming and not outgoing:
        empty_marker = empty_state_html("empty-requests", "No requests yet.",
                                         cta_label="Go to Home to request money", cta_href="/")
    incoming_html = "".join(_request_item_html(r, user["id"], minor_units) for r in incoming)
    outgoing_html = "".join(_request_item_html(r, user["id"], minor_units) for r in outgoing)
    return f"""<section class="placeholder-card">
  <h1>Requests</h1>
  {empty_marker}
  <div data-testid="request-error-slot" class="form-slot"></div>
  <h2>Incoming</h2>
  <div data-testid="incoming-list" class="list">{incoming_html}</div>
  <h2>Outgoing</h2>
  <div data-testid="outgoing-list" class="list">{outgoing_html}</div>
</section>"""
