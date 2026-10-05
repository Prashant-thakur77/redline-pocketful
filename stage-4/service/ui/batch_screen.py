"""The `/correction-batches` screen — R-U-039.

Negotiated with the existing JSON `POST /correction-batches` (R-U-041):
this module only ever renders for `GET` with `Accept: text/html`; there
is no JSON `GET` registered for this path either, so a non-HTML `GET`
still falls through to the ordinary router's 405, unchanged.

The operator gate (R-U-039, planner ruling 5) is read straight out of
`STORE.settlement_operator_ids` -- the same set `CorrectionBatchEndpoint`
itself checks -- never from a client-visible flag, since `GET /me` must
not gain an operator field (R-U-001). A non-operator who navigates here
directly gets the same clean "not available" state a third party gets on
a payment detail page, never a hidden button or a disabled control.
"""
from __future__ import annotations

from ..store import STORE

_MAX_ROWS = 32


def render_batch_body(user: dict) -> str:
    if user["id"] not in STORE.settlement_operator_ids:
        return """<section class="placeholder-card">
  <h1>Correction batch</h1>
  <p data-testid="batch-unavailable" class="empty-state">This screen is not available.</p>
</section>"""

    return f"""<section class="placeholder-card" id="batch-screen" data-row-count="0" data-max-rows="{_MAX_ROWS}">
  <h1>Correction batch</h1>
  <table data-testid="batch-table" class="batch-table">
    <thead>
      <tr><th>Payment id</th><th>Amount</th><th>Reason</th><th>Expected revision</th>
          <th>Effective at</th><th></th></tr>
    </thead>
    <tbody data-testid="batch-tbody"></tbody>
  </table>
  <p data-testid="empty-batch" class="empty-state">No rows yet -- add one to begin.</p>
  <button type="button" data-testid="batch-add" class="btn btn-ghost">Add row</button>
  <div data-testid="batch-preview" class="form-review" aria-live="polite" hidden></div>
  <button type="button" data-testid="batch-submit" class="btn btn-primary">Submit batch</button>
  <div data-testid="batch-result" class="form-slot" hidden></div>
  <div data-testid="batch-error" class="form-slot" hidden></div>
  <div data-testid="batch-uncertain" class="form-slot" hidden></div>
</section>"""
