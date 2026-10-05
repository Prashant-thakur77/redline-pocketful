"""The `/split` screen — R-2-135, R-2-136. The preview is computed
entirely client-side (`static/app.js`) using the exact §9 share rule
(`base, rem = divmod(amount, n)`, share `i` is `base+1` for `i < rem`)
so it matches what `POST /splits` (`SplitsEndpoint.apply`) would
actually return, before anything is posted.
"""
from __future__ import annotations


def render_split_body() -> str:
    return """<section class="placeholder-card">
  <h1>Split a bill</h1>
  <form data-testid="split-form" data-state="idle" class="form" novalidate>
    <label class="field">
      <span class="field-label">Amount</span>
      <input type="text" name="amount" data-testid="split-amount">
    </label>
    <label class="field">
      <span class="field-label">Participants (handles, comma-separated)</span>
      <input type="text" name="handles" data-testid="split-handles">
    </label>
    <label class="field">
      <span class="field-label">Note</span>
      <input type="text" name="note" data-testid="split-note">
    </label>
    <button type="submit" data-testid="split-submit" class="btn btn-primary">Split</button>
  </form>
  <div data-testid="split-error-slot" class="form-slot"></div>
  <div data-testid="split-preview" class="split-preview" data-state="empty"></div>
</section>"""
