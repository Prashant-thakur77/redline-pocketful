"""The `/payments/{id}` screen — R-U-034..038.

There is no documented `GET /payments/{id}` (R-U-001 forbids inventing
one), so this path is matched by pattern in `ui/__init__.py` and ONLY
ever diverted here on an explicit `Accept: text/html` -- every other
caller gets exactly what the service returns today for this path (a 404
from `ROUTER`, since nothing is registered at it).

The permission check this screen must enforce (R-U-034: only the two
parties, 404 for a third party even on a public payment) is not
reimplemented here -- `PaymentRevisionsEndpoint.check_resource_permission`
already raises `not_found` for exactly that case, and calling it through
`call_authed` the same way every other SSR page calls a real endpoint
object (R-2-185) is the one and only authorization check this module
performs. Once that call succeeds the caller is a party by construction,
so reading the payment's own fields out of `STORE` for display (parties,
note, refunded_total) is a read of data already proven visible, in the
same shape `serialize_payment` already exposes elsewhere -- never a
second, looser permission rule.
"""
from __future__ import annotations

from ..errors import ApiError
from ..revisions import latest_revision
from ..routes.payments import serialize_payment
from ..routes.revisions import PaymentRevisionsEndpoint
from ..store import STORE
from .calls import call_authed
from .layout import empty_state_html, esc, format_amount

_REVISIONS_ENDPOINT = PaymentRevisionsEndpoint()


def _revision_item_html(rev: dict, currency: str, minor_units: int) -> str:
    n = rev["revision"]
    reason = rev.get("reason") or ("original payment" if n == 1 else "")
    amount_fmt = esc(format_amount(rev["amount"], currency, minor_units))
    return f"""<article data-testid="revision-item-{n}" class="list-item">
  <p data-testid="revision-amount-{n}" class="list-item-amount">{amount_fmt}</p>
  <p data-testid="revision-reason-{n}" class="list-item-note">{esc(reason)}</p>
  <p data-testid="revision-effective-{n}" class="list-item-note">{esc(rev["effective_at"])}</p>
</article>"""


def _refund_item_html(refund: dict, currency: str, minor_units: int) -> str:
    amount_fmt = esc(format_amount(refund["amount"], currency, minor_units))
    return f"""<article data-testid="refund-item-{esc(refund["id"])}" class="list-item">
  <p class="list-item-amount">{amount_fmt}</p>
  <p class="list-item-note">{esc(refund["created_at"])}</p>
</article>"""


def _unavailable_html() -> str:
    return ('<p data-testid="payment-detail-unavailable" class="empty-state">'
            'This payment is not available.</p>')


def render_payment_detail_body(payment_id: str, user: dict, token: str) -> str:
    try:
        _, data = call_authed(_REVISIONS_ENDPOINT, "GET", f"/payments/{payment_id}/revisions", token,
                               path_params={"id": payment_id})
    except ApiError:
        # R-U-034: a third party (even on a public payment) sees this
        # exact clean state, never a crash or a blank page -- the same
        # outcome `PaymentRevisionsEndpoint` itself returns (404) for an
        # unknown payment or a non-party, indistinguishable by design
        # (R-1-078's hide-as-404 rule).
        return f"""<section class="placeholder-card" data-testid="payment-detail-{esc(payment_id)}">
  <h1>Payment</h1>
  {_unavailable_html()}
</section>"""

    revisions = sorted(data["revisions"], key=lambda r: r["revision"])
    payment = STORE.payments.get(payment_id)
    currency, minor_units = STORE.currency, STORE.minor_units
    serialized = serialize_payment(payment)

    revisions_html = ("".join(_revision_item_html(r, currency, minor_units) for r in revisions) if revisions
                       else empty_state_html("empty-revisions", "No revision history."))

    refunds = [p for p in STORE.payments.values() if p.get("refund_of") == payment_id]
    refunds.sort(key=lambda p: p["seq"])
    refund_list_html = ("".join(_refund_item_html(r, currency, minor_units) for r in refunds)
                         if refunds else '<p class="list-item-note">No refunds yet.</p>')

    current_amount = latest_revision(revisions)["amount"] if revisions else payment["amount"]
    already_refunded = payment.get("refunded_total", 0)
    remaining = max(0, current_amount - already_refunded)
    remaining_fmt = esc(format_amount(remaining, currency, minor_units))

    remaining_decimal = format_amount(remaining, currency, minor_units).split(" ")[0]

    is_receiver = payment["to_user_id"] == user["id"]
    is_sender = payment["from_user_id"] == user["id"]
    refund_action_html = ""
    if is_receiver and payment.get("refund_of") is None and remaining > 0:
        refund_action_html = f"""<section class="form-card">
  <h3>Refund</h3>
  <form data-testid="refund-form" class="form" novalidate>
    <p class="list-item-note">Remaining refundable: <span data-testid="refund-remaining">{remaining_fmt}</span></p>
    <label class="field">
      <span class="field-label">Amount</span>
      <input type="text" data-testid="refund-amount" value="{remaining_decimal}">
    </label>
    <div data-testid="refund-review" class="form-review" aria-live="polite" hidden></div>
    <button type="button" data-testid="refund-submit" class="btn btn-primary">Refund</button>
  </form>
  <div data-testid="refund-error" class="form-slot" hidden></div>
  <div data-testid="refund-uncertain" class="form-slot" hidden></div>
</section>"""

    correct_action_html = ""
    linked = (payment.get("settlement_id") is not None or payment.get("authorization_id") is not None
              or payment.get("refund_of") is not None)
    if is_sender and not linked:
        last_rev = revisions[-1]
        last_amount_decimal = format_amount(last_rev["amount"], currency, minor_units).split(" ")[0]
        correct_action_html = f"""<section class="form-card">
  <h3>Correct</h3>
  <form data-testid="correct-form" class="form" novalidate>
    <input type="hidden" data-testid="correct-expected-revision" value="{last_rev["revision"]}">
    <label class="field">
      <span class="field-label">New amount</span>
      <input type="text" data-testid="correct-amount" value="{last_amount_decimal}">
    </label>
    <label class="field">
      <span class="field-label">Reason</span>
      <input type="text" data-testid="correct-reason">
    </label>
    <label class="field">
      <span class="field-label">Effective at</span>
      <input type="datetime-local" data-testid="correct-effective">
    </label>
    <div data-testid="correct-review" class="form-review" aria-live="polite" hidden></div>
    <button type="button" data-testid="correct-submit" class="btn btn-primary">Correct</button>
  </form>
  <div data-testid="correct-error" class="form-slot" hidden></div>
  <div data-testid="correct-uncertain" class="form-slot" hidden></div>
</section>"""

    return f"""<section class="placeholder-card" data-testid="payment-detail-{esc(payment_id)}"
         data-payment-id="{esc(payment_id)}" data-currency="{esc(currency)}" data-minor-units="{minor_units}">
  <h1>Payment</h1>
  <p class="list-item-parties">{esc(serialized["from_handle"] or payment["from_user_id"])}
     &rarr; {esc(serialized["to_handle"] or payment["to_user_id"])}</p>
  <h2>Revisions</h2>
  <div data-testid="revision-list" class="list">{revisions_html}</div>
  <h2>Refunds</h2>
  <div data-testid="refund-list" class="list">{refund_list_html}</div>
  {refund_action_html}
  {correct_action_html}
</section>"""
