"""The `/authorizations` screen — R-2-137, R-2-138. SSR only; capture/
void are bound and re-rendered by `static/app.js`, calling the exact
`/authorizations/{id}/capture|void` routes (R-2-185).
"""
from __future__ import annotations

from ..routes.authorizations_read import AuthorizationsListEndpoint
from ..store import STORE
from .calls import call_authed
from .layout import empty_state_html, esc, format_amount

_AUTHORIZATIONS_LIST = AuthorizationsListEndpoint()


def _actions_html(a: dict, user_id: str, minor_units: int) -> str:
    if a["status"] != "open":
        return ""
    aid = a["authorization_id"]
    if a["to_user_id"] == user_id:
        remaining_fmt = format_amount(a["remaining_amount"], a["currency"], minor_units)
        return (f'<label class="field capture-field">'
                f'<span class="field-label">Capture amount</span>'
                f'<input type="text" data-testid="authorization-capture-amount-{esc(aid)}" value="{esc(remaining_fmt.split()[0])}">'
                f'</label>'
                f'<button type="button" data-testid="authorization-capture-{esc(aid)}" '
                f'data-action="capture" data-id="{esc(aid)}" class="btn btn-primary">Capture</button>')
    if a["from_user_id"] == user_id:
        return (f'<button type="button" data-testid="authorization-void-{esc(aid)}" '
                f'data-action="void" data-id="{esc(aid)}" class="btn btn-ghost">Void</button>')
    return ""


def _authorization_item_html(a: dict, user_id: str, minor_units: int) -> str:
    aid = a["authorization_id"]
    is_payer = a["from_user_id"] == user_id
    counterpart = a["to_handle"] if is_payer else a["from_handle"]
    amount_fmt = esc(format_amount(a["amount"], a["currency"], minor_units))
    captured_html = ""
    if a["captured_amount"] > 0:
        captured_fmt = esc(format_amount(a["captured_amount"], a["currency"], minor_units))
        captured_html = (f'<p data-testid="authorization-captured-{esc(aid)}" '
                          f'class="list-item-captured">{captured_fmt}</p>')
    return f"""<article data-testid="authorization-item-{esc(aid)}" data-status="{esc(a["status"])}" class="list-item">
  <p class="list-item-parties">{esc(counterpart or "?")}</p>
  <p data-testid="authorization-amount-{esc(aid)}" class="list-item-amount">{amount_fmt}</p>
  {captured_html}
  <p data-testid="authorization-expires-{esc(aid)}" class="list-item-expires">{esc(a["expires_at"])}</p>
  <p class="list-item-note">{esc(a["note"])}</p>
  <div class="list-item-actions">{_actions_html(a, user_id, minor_units)}</div>
</article>"""


def render_authorizations_body(user: dict, token: str) -> str:
    _, data = call_authed(_AUTHORIZATIONS_LIST, "GET", "/authorizations", token, query={"limit": "200"})
    authorizations = data["authorizations"]
    minor_units = STORE.minor_units
    # R-2-137: authorization-list stays in the DOM even when empty — same
    # fix as /requests (gate-3 finding): collapsing the whole page to a
    # placeholder when empty makes the list container vanish along with
    # the content, so a direct navigation to this route for a user with
    # no holds times out waiting for an element that never existed.
    empty_marker = ""
    if not authorizations:
        empty_marker = empty_state_html("empty-authorizations", "No authorizations yet.",
                                         cta_label="Go to Home to authorize a hold", cta_href="/")
    items_html = "".join(_authorization_item_html(a, user["id"], minor_units) for a in authorizations)
    return f"""<section class="placeholder-card">
  <h1>Authorizations</h1>
  {empty_marker}
  <div data-testid="authorization-error-slot" class="form-slot"></div>
  <div data-testid="authorization-list" class="list">{items_html}</div>
</section>"""
