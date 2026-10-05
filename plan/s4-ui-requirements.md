# Stage 4 browser-product requirements (operator note 4)

Source: operator note 4, 2026-10-06, disclosed human instruction in the room. **`stage-4/` only** —
`stage-1/`, `stage-2/` and `stage-3/` are frozen.

This is **new scope from the operator**, not a reversal of the earlier cancellation of N4-7/N4-C5.
That cancellation was correct against the specification: `stage-3.md` and `stage-4.md` contain zero
`data-testid`, `browser`, `screen` or `route` occurrences, so no *spec* requires these screens. The
operator now requires them anyway, which is their call to make. Both statements stand.

Ids are `R-U-nnn`. Every R-1-*, R-2-*, R-3-* and R-4-* requirement continues to apply unchanged.

## A. Hard constraints — these outrank every item below

| id | requirement | kind |
|---|---|---|
| R-U-001 | **No API behaviour change of any kind.** No endpoint gains, loses or alters a status code, body field, error code or precedence. The screens call the existing JSON endpoints only. | invariant |
| R-U-002 | **No browser-only write path** (R-2-185). Every write the UI performs is an ordinary call to a documented endpoint with an `Idempotency-Key` where that endpoint requires one. | invariant |
| R-U-003 | Every existing route keeps serving: `/`, `/requests`, `/split`, `/signup`, `/login`, `/authorizations`, and content negotiation is unchanged — HTML for `Accept: text/html`, JSON otherwise. | invariant |
| R-U-004 | **Every existing `data-testid` keeps its exact id and its exact semantics.** Text that a test asserts exactly (`wallet-balance`, `activity-amount-{id}`, `request-amount-{id}`, `split-share-{handle}`, `current-handle`, `authorization-amount-{id}`) keeps that exact text and its `data-amount` attribute where it has one. | invariant |
| R-U-005 | **PLANNER DECISION — the binding constraint, and the one most likely to be missed.** `stage-1/`, `stage-2/` and `stage-3/` are frozen but their test suites are **executed against `stage-4/`'s service by gate 5** (`g5_regression.py:52`). Those suites contain UI tests that fill and click existing ids **without knowing about any new toggle, tab or panel**. Therefore every existing form field and button must remain **present in the DOM and directly interactable on its documented route, with no preceding interaction required**. A toggle may change visual prominence, ordering, grouping or styling; it may **not** gate an existing element behind a click, a tab change, or `display: none`. If A2's single-primary-action design cannot be built within that rule, the rule wins and the design adapts. | invariant |
| R-U-006 | Gate 7 stays clean at 375, 768 and 1280 CSS px: no horizontal page scrolling, no control under 24 px, no serious axe violation, no external asset, and empty/loading/error states present on every list. | invariant |
| R-U-007 | Gates 2, 4 and 3 (the task harness) must not regress. The suite stays green and the test-count ratchet is never reduced. | invariant |
| R-U-008 | All runtime assets stay inside the image — no external font, script, stylesheet or icon CDN (R-1-013). A logo mark and icons are inline SVG or bundled. | invariant |

## B. Polish what exists

| id | requirement | from |
|---|---|---|
| R-U-010 | Wallet shows one large **Available** figure, with labelled **Total** and **On hold** lines beneath it, visibly secondary. `wallet-available` remains the headline (R-2-128). | A1 |
| R-U-011 | Amounts render with the currency symbol where one exists for the fixture's currency (`€40.00`), with consistent signs and colours. **`wallet-balance`, `activity-amount-{id}`, `request-amount-{id}`, `split-share-{handle}` and `authorization-amount-{id}` keep their exact existing `"<decimal> <CODE>"` text** (R-2-121, R-U-004); the symbol presentation goes in *additional* elements, never by changing those. | A1, R-U-004 |
| R-U-012 | Home presents **one primary Pay / Request action with a toggle**, not three full forms at once, ordered **amount first in large type, then recipient, then note**. Subject to R-U-005: all of `pay-*`, `request-*` and `authorize-*` stay in the DOM and directly interactable. | A2 |
| R-U-013 | The authorize-a-hold form stays reachable as a secondary action or its own panel, with every existing id intact. | A2 |
| R-U-014 | A **review step** shows recipient, amount and note before a payment is sent, and a clear success or failure state after it. The review step must not break R-2-151 (resubmitting an unchanged form sends no second payment) or R-2-158 (same key and body on retry after `pay-uncertain`). | A3 |
| R-U-015 | Activity feed reads as `"Maya paid Leo · Dinner · 2h"` with avatar initials, money in (`+`, green) or out (`−`, grey) **from the signed-in user's point of view**, grouped by day. Newest-first DOM order (R-2-130) and the exact-text ids are preserved. | A4 |
| R-U-016 | At 375 px: a bottom tab bar and a single-row header, with one action visible at a time. | A5 |
| R-U-017 | Every list has an empty state with an icon, one sentence and a call to action — including the existing `empty-activity`, `empty-requests`, `empty-authorizations`, which keep their ids. | A6 |
| R-U-018 | Split shows participants as **removable chips** with a live per-person share preview beside them. `split-handles` stays a fillable text input of comma-separated handles (R-U-005), and `split-preview` / `split-share-{handle}` keep exact share text matching the server's §9 rule. | A7 |
| R-U-019 | A small logo mark, one accent colour used consistently, and `prefers-color-scheme: dark` respected. Contrast must hold in both schemes for gate 7's axe pass. | A8 |

## C. Give the newer stages a face

| id | requirement | from |
|---|---|---|
| R-U-030 | **Statement screen** at a new route: pick a date window, entries grouped by day with running balance. Reads `GET /statement` only. | B9 |
| R-U-031 | An **"as of" date picker** showing the balance on any past day, calling `GET /me?as_of=`. | B9 |
| R-U-032 | A **"what we knew then" (`known_at`) toggle**, calling the existing `known_at` parameter. The two axes are independent (R-3-074): `as_of` and `known_at` may be set together and the UI must not conflate them. | B9 |
| R-U-033 | Paging through a **frozen snapshot** with a visible "snapshot taken at …" note, using the `snapshot` token. Only `limit`/`offset` may accompany it (R-3-083). | B9 |
| R-U-034 | **Payment detail screen**: the payment's revision history as a timeline (original, then each correction with reason and effective date), from `GET /payments/{id}/revisions`. | B10 |
| R-U-035 | Payment detail shows the **refunds against it and the remaining refundable amount**, derived from the payment's current corrected amount minus cumulative refunds. | B10 |
| R-U-036 | **Refund action** where the signed-in user is the receiver: full or partial, with the remaining amount prefilled, via `POST /payments/{id}/refunds` with an `Idempotency-Key`. | B11 |
| R-U-037 | **Correct action** where permitted: amount, reason, effective date, via `POST /payments/{id}/corrections` with an `Idempotency-Key`. | B11 |
| R-U-038 | Both actions use the R-U-014 review step, and **show the API's error text plainly when refused** — including `refund_exceeds_payment`, `linked_payment_immutable`, `insufficient_funds`, `historical_overdraft`, `stale_revision`. Never present a refusal as a success, and never present an unknown outcome as a refusal (R-2-157). | B11 |
| R-U-039 | **Batch corrections for the operator role**: a small table of pending corrections, a combined preview, submit as one batch via `POST /correction-batches`, and the **all-or-nothing result shown clearly**. Visible only to a settlement operator; a non-operator must not see the entry point. | B12 |
| R-U-040 | Every new screen has `data-testid`s, empty/loading/error states, keyboard access and visible focus. | B13 |
| R-U-041 | **PLANNER DECISION.** New routes are additive and must serve HTML for `Accept: text/html` and JSON otherwise **only if** they shadow an existing API path. A screen with no API twin (e.g. a statement screen at `/statement` shares the path with `GET /statement`) must preserve the JSON response for non-HTML callers exactly — that endpoint is tested by the frozen suites. | R-U-003 |
| R-U-042 | **PLANNER DECISION.** Every browser write reuses the idempotency discipline the API already requires: a key derived from the form's content so an unchanged resubmit replays rather than duplicates (R-2-151), and a changed field produces a new key (R-2-152). This applies to refunds, corrections and batches exactly as it already does to payments. | R-U-002 |

## D. Evidence

| id | requirement |
|---|---|
| R-U-050 | Before/after gate 7 screenshots recorded in `plan/s4-status.md`. The **before** set is the g7 output of the stage-4 close run, already scheduled — no separate capture needed. |
| R-U-051 | Each item is attacked by @adversary on **every new browser write path**: double submit, stale page, retry after a lost response. |
| R-U-052 | @verifier re-runs **all** gates after each item, not a subset. |
