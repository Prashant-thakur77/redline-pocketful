# Stage 4 requirements — pocketful: refunds and batch corrections

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-4.md`.
`§` references are to `stage-1.md` unless prefixed `s2`/`s3`/`s4`.

**Every requirement in `plan/s1-requirements.md`, `plan/s2-requirements.md` and
`plan/s3-requirements.md` continues to apply unchanged in `stage-4/`**, except where a row
below amends one. Amendments: R-1-100 / R-2-016 / R-3-050 (**ten** idempotent write paths),
R-3-058 (correction debits now checked against `available`), R-3-065/066 (the immutable set
gains refunds).

## A. Invariants — stage 4 adds four; stages 1–3 still hold

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-001 | A refund moves **existing** money in the opposite direction; it never creates or destroys any. The sum of all balances still equals the seeded total, currently and in every historical view. | s4 §Refunds | invariant |
| R-4-002 | Cumulative refunds against one payment never exceed that payment's **current corrected** amount, under any interleaving of refunds and corrections. | s4 §Refunds | invariant |
| R-4-003 | A batch correction is all-or-nothing: either every revision in it commits or none does, and a rejected batch leaves history, balances, snapshots and idempotency records exactly as they were. | s4 §Batch corrections | invariant |
| R-4-004 | Original payments, original receipts and previously issued snapshot tokens are never changed by a refund or a batch correction. | s4 §Batch corrections | invariant |

## B. Refunds

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-010 | `POST /payments/{payment_id}/refunds` with body `{"amount": N}` requires an `Idempotency-Key`. It is the ninth idempotent write path. | s4 §Refunds | behaviour |
| R-4-011 | Only the original **receiver** of the target payment may refund it; an authenticated non-receiver is `403 forbidden`; no token is `401 unauthenticated`; an unknown payment is `404 not_found`. | s4 §Refunds | error |
| R-4-012 | The target may be a direct payment, a request payment or a capture. | s4 §Refunds | behaviour |
| R-4-013 | A refund of a refund is `422 invalid_refund_target`. | s4 §Refunds | error |
| R-4-014 | An invalid `amount` is `422 validation_failed`, by the ordinary amount rules (R-1-134: integral, 1..1000000000). | s4 §Refunds | error |
| R-4-015 | Refunds cumulatively exceeding the payment's **current corrected** amount are `422 refund_exceeds_payment`. | s4 §Refunds | error |
| R-4-016 | A refund is a new payment in the opposite direction, carrying `refund_of` naming the target, `request_id: null`, `authorization_id: null`, and the **original** note and visibility. | s4 §Refunds | behaviour |
| R-4-017 | Success is `201` with that payment; a replay is `200` with the original body. | s4 §Refunds | behaviour |
| R-4-018 | A refund moves money from the receiver's **available** funds, atomically, or fails `409 insufficient_funds`. | s4 §Refunds | behaviour |
| R-4-019 | A refund never reopens a request or an authorization, and never restores a released hold. | s4 §Refunds | invariant |
| R-4-020 | Every payment that is not a refund exposes `refund_of: null`. | s4 §Refunds | behaviour |
| R-4-021 | A settlement member payment may be refunded under the ordinary rules, and a refund never changes settlement membership. | s4 §Batch corrections | behaviour |
| R-4-022 | **PLANNER DECISION.** Refund error precedence, extending R-1-075 and R-3-068: `401` → `404 not_found` (unknown payment) → `403 forbidden` (non-receiver) → `400 missing_idempotency_key` → idempotency resolution → `422 validation_failed` (amount) → `422 invalid_refund_target` (target is a refund) → `422 refund_exceeds_payment` → `409 insufficient_funds`. Target-kind and cumulative-total checks precede funds because they are properties of the target, not of the wallet. | s4 §Refunds, §5 | error |
| R-4-023 | **PLANNER DECISION.** A refund appears in `GET /activity` and in both parties' statements as an ordinary payment, by the ordinary visibility and statement rules, and carries its own revision 1 (R-3-015). Nothing in s4 exempts it. | s4 §Refunds, s3 | behaviour |
| R-4-024 | **PLANNER DECISION.** `refund_of` is the id of the **immediately targeted** payment. Since a refund may not target a refund (R-4-013), no chain deeper than one level can exist. | s4 §Refunds | behaviour |

## C. Corrections after refunds

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-030 | Stage-3 corrections remain available for ordinary direct and request payments. | s4 §Refunds | behaviour |
| R-4-031 | A capture cannot be corrected: `422 linked_payment_immutable` (carried R-3-066). | s4 §Refunds | error |
| R-4-032 | A **refund** payment cannot itself be corrected: `422 linked_payment_immutable`. | s4 §Refunds | error |
| R-4-033 | A correction may not reduce a payment below its already-refunded amount: `422 refund_exceeds_payment`. | s4 §Refunds | error |
| R-4-034 | Correction debits are checked against **available** funds, not total — amending R-3-058's affordability test. | s4 §Refunds | behaviour |
| R-4-035 | **PLANNER DECISION (added 17:55, ruling a gap @builder surfaced in N4-1).** For a **single** correction, the refunded-amount floor outranks both funds checks: `422 refund_exceeds_payment` (R-4-033) precedes `409 insufficient_funds` (R-3-059) which precedes `409 historical_overdraft` (R-3-060). Rationale: R-4-049 fixes exactly this order for batches — item errors, then current available funds, then historical boundaries — and lists the codes in that sequence; a single correction is a one-item batch, so the same order is the only reading consistent with both. A correction reducing a payment below its refunded total must therefore report `refund_exceeds_payment` even when the same arithmetic would also produce a historical overdraft. | s4 §Batch corrections, §Refunds | error |

## D. Batch corrections

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-040 | `POST /correction-batches` requires a settlement operator and an `Idempotency-Key`, with the same `401`/`403` rules as `POST /settlements` (R-1-221). It is the tenth idempotent write path. | s4 §Batch corrections | behaviour |
| R-4-041 | The body is `{"corrections": [{payment_id, expected_revision, amount, effective_at, reason}, …]}` with 1 to 32 objects having **distinct** `payment_id`s; otherwise `422 validation_failed`. | s4 §Batch corrections | error |
| R-4-042 | Every item carries the ordinary correction fields and the ordinary per-field validation (R-3-052, R-3-053). | s4 §Batch corrections | error |
| R-4-043 | An unknown `payment_id` is `404 not_found`; a stale `expected_revision` is `409 stale_revision`. | s4 §Batch corrections | error |
| R-4-044 | The operator may correct ordinary, request and **settlement** payments; captures and refunds remain immutable (`422 linked_payment_immutable`). | s4 §Batch corrections | error |
| R-4-045 | Correcting any settlement member requires including **every** member of that settlement in the same batch; otherwise `422 incomplete_settlement`. | s4 §Batch corrections | error |
| R-4-046 | Members of one settlement must carry identical effective instants — offset spellings may differ, the instant may not — otherwise `422 validation_failed`. | s4 §Batch corrections | error |
| R-4-047 | Ordinary single-payment corrections remain available for payments that are not settlement members. | s4 §Batch corrections | behaviour |
| R-4-048 | Unknown fields in the batch body and in each item are ignored (R-1-022). | s4 §Batch corrections | behaviour |
| R-4-049 | Batch error precedence is exactly: item errors **in input order** → settlement completeness → resulting **current available** funds → historical **total and available** at every effective/event boundary. The codes are `linked_payment_immutable`, `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft`. | s4 §Batch corrections | error |
| R-4-050 | Affordability is determined by the **combined** effect of all proposed revisions, not by each in isolation. | s4 §Batch corrections | behaviour |
| R-4-051 | A rejected batch leaves history, balances and idempotency records unchanged and claims no key. | s4 §Batch corrections | invariant |
| R-4-052 | Success is `201` with `correction_batch_id`, `recorded_at` and `revisions` in **input order**. | s4 §Batch corrections | behaviour |
| R-4-053 | All new revisions in a batch share one `recorded_at`, strictly later than the previous `recorded_at` of **every** member (preserving R-3-004 per payment). | s4 §Batch corrections | invariant |
| R-4-054 | Each revision created by a batch exposes `correction_batch_id`; revisions created singly expose `null` for it. | s4 §Batch corrections | behaviour |
| R-4-055 | Effective times cannot be later than now (R-3-053). | s4 §Batch corrections | error |
| R-4-056 | Original payments and receipts never change; original payment and settlement **retries** still return their original bodies. | s4 §Batch corrections | behaviour |
| R-4-057 | New statements reflect the new revisions, while **earlier snapshot tokens continue to page their frozen entries** (R-3-005, R-3-088). | s4 §Batch corrections | invariant |
| R-4-058 | A batch replay returns the original batch response with `200`. | s4 §Batch corrections | behaviour |
| R-4-059 | Concurrent corrections sharing **any** expected payment revision cannot both succeed — across single corrections and batches alike. | s4 §Batch corrections | invariant |
| R-4-060 | **PLANNER DECISION.** `incomplete_settlement` is checked after every per-item error in input order (R-4-049 states this), so a batch that is both incomplete and contains an invalid item reports the **item** error. Completeness is evaluated over the union of settlements touched by the batch. | s4 §Batch corrections | error |
| R-4-061 | **PLANNER DECISION.** A batch containing two items for the same `payment_id` is `422 validation_failed` under R-4-041's distinctness rule, and that check runs with the per-item errors of R-4-049's first stage, in input order. | s4 §Batch corrections | error |

## E. Upgrade and carried behaviour

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-070 | A stage-4 service accepts, unchanged, exports produced by the team's stage-1, stage-2 **or** stage-3 service, retaining settlement membership, corrections and snapshots. | s4 §Batch corrections | behaviour |
| R-4-071 | There are exactly ten idempotent write paths: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`, `POST /authorizations`, `POST /authorizations/{id}/capture`, `POST /payments/{id}/corrections`, `POST /payments/{id}/refunds` and `POST /correction-batches`. All of §7 applies to each independently. | s4 §intro | behaviour |
| R-4-072 | Existing receipts and saved statements remain available in their original form. | s4 §intro | invariant |

## F. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-080 | A storm mixing every write path with ~30% replays preserves R-4-001…004, R-3-001…005, R-2-001…005 and R-1-001…007. | s4, s3, s2 | invariant |
| R-4-081 | Two concurrent refunds that together would exceed the payment's current corrected amount cannot both succeed. | s4 §Refunds | invariant |
| R-4-082 | A refund racing a correction of the same payment cannot leave cumulative refunds above the corrected amount, nor either balance negative. | s4 §Refunds | invariant |
| R-4-083 | Two concurrent batches sharing any payment cannot both succeed (R-4-059). | s4 §Batch corrections | invariant |
