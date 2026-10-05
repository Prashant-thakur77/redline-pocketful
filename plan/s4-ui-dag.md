# Stage 4 browser-product work plan (operator note 4)

Three items, as the operator asked for "two or three". `stage-4/` only.
**Nothing dispatches until stage 4's close is recorded** — the close run's g7 output is the
mandatory "before" screenshot set (R-U-050), and dispatching sooner would also disturb the
most expensive run in the stage.

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| U1 | Design system and shell: brand mark, accent colour, dark scheme, typography/spacing, wallet figures, 375 px bottom tab bar and single-row header, empty states on every list | R-U-001…008, R-U-010, R-U-011, R-U-016, R-U-017, R-U-019 | close recorded | builder |
| U2 | Primary flow: home single primary Pay/Request action with amount-first ordering, review step, success/failure states, activity feed lines with initials and day grouping, split chips with live share preview, authorize panel | R-U-012, R-U-013, R-U-014, R-U-015, R-U-018, R-U-042 | U1 | builder |
| U3 | A face for stages 3–4: statement screen with window/`as_of`/`known_at`/snapshot paging, payment detail with revision timeline and refunds, refund and correct actions, operator batch-correction table | R-U-030…041 | U2 | builder |

After **each** item: @verifier runs `--gates all` (R-U-052); @adversary attacks every new browser
write path — double submit, stale page, retry after a lost response (R-U-051). U3 is where the new
write paths appear (refund, correct, batch), so it carries the heaviest attack pass.

## The constraint that will decide whether this lands

**R-U-005.** `stage-1/`, `stage-2/` and `stage-3/` are frozen, but gate 5 executes their suites
against `stage-4/`'s service. Those suites fill and click existing ids with no knowledge of any new
toggle or tab. So every existing field and button must stay **present and directly interactable on its
documented route with no preceding interaction**. A toggle may restyle, reorder or group; it may not
hide an element behind a click or `display: none`.

This bites hardest on U2's "one primary action instead of three forms at once". The resolution is
fixed in advance so no seat has to guess: **visual prominence may change, DOM availability may not.**
Expect a layout where the non-primary forms are present and usable but visually secondary, rather than
tabbed away.

Second-hardest: U1's dark scheme must keep contrast passing axe in **both** schemes, and U1's currency
symbols must not touch the exact-text ids (R-U-011) — the symbol goes in additional elements, never by
rewriting `wallet-balance` or `activity-amount-{id}`.

## Order of dispatch

`close recorded` → U1 → gates+attack → U2 → gates+attack → U3 → gates+attack → final report.

If the clock ends mid-sequence, the honest outcome is U1 (and U2) landed with U3 absent, reported as
such — the same rule as every other stage: a partial that is disclosed beats a stalled one. The money
paths are already complete and are not touched by any of this.
