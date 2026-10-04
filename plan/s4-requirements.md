# Stage 4 requirements — pocketful: refunds and batch corrections

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-4.md`.
`§` references are to `stage-1.md` unless prefixed `s2`/`s3`/`s4`.

**Every requirement in `plan/s1-requirements.md`, `plan/s2-requirements.md` and
`plan/s3-requirements.md` continues to apply in `stage-4/`**, except where a row below
amends one. Stage 4's checks are mostly hidden, so rows marked **[derived]** — things no
example shows — carry the same weight as the rest.

Kinds: **invariant**, **behaviour**, **error**, **limit**, **UI**.

## A. Invariants

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-001 | A refund moves **existing** money: the sum of all balances still equals the seeded total, in every historical view, after any mix of refunds, corrections and correction batches. | s4 §Refunds | invariant |
| R-4-002 | A refund never creates money: cumulative refunds on a payment never exceed that payment's **current corrected** amount. | s4 §Refunds | invariant |
| R-4-003 | A refund is atomic: it either moves the money and records the refund payment, or does neither. | s4 §Refunds | invariant |
| R-4-004 | Original payments, receipts and idempotent responses are never changed by a refund, a correction or a batch — ever. | s4 §Batch | invariant |
| R-4-005 | A rejected batch leaves history, balances and idempotency records exactly as they were. | s4 §Batch | invariant |
| R-4-006 | Earlier `snapshot` tokens continue to page their frozen entries after any refund, correction or batch (R-3-009 extended). | s4 §Batch | invariant |
| R-4-007 | Concurrent corrections sharing **any** expected payment revision cannot both succeed. | s4 §Batch | invariant |
| R-4-008 | There are exactly **ten** idempotent write paths: stage 1's five, authorizations and captures (stage 2), corrections (stage 3), and refunds and correction batches (stage 4). §7 applies to each independently. | s4 intro | behaviour |
| R-4-009 | **[derived]** No balance — `total` or `available` — is negative at any effective/event boundary in any view, after any refund or batch. | s4 §Batch, s3 | invariant |

## B. Refunds

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-020 | `POST /payments/{payment_id}/refunds` with body `{"amount": <int>}` requires an `Idempotency-Key`. | s4 §Refunds | behaviour |
| R-4-021 | Only the **original receiver** of the target payment may refund it; an authenticated non-receiver is `403 forbidden`; an unknown payment is `404 not_found`; no token is `401 unauthenticated`. | s4 §Refunds | error |
| R-4-022 | The target may be a direct payment, a request payment or a **capture**, but never a refund. | s4 §Refunds | behaviour |
| R-4-023 | A refund whose target is itself a refund is `422 invalid_refund_target`. | s4 §Refunds | error |
| R-4-024 | An invalid `amount` is `422 validation_failed`. **[derived]** That means below 1, above 1000000000, non-integral, or of a non-numeric JSON type (R-1-032, R-1-069 apply). | s4 §Refunds | error |
| R-4-025 | Cumulative refunds may not exceed the payment's **current corrected** amount: `422 refund_exceeds_payment`. | s4 §Refunds | error |
| R-4-026 | Success is `201` with the refund payment; a replay returns `200` with the original body. | s4 §Refunds | behaviour |
| R-4-027 | A refund is a **new payment in the opposite direction**: `from` is the original receiver, `to` is the original sender. | s4 §Refunds | behaviour |
| R-4-028 | The refund payment carries `refund_of` naming the target payment, `request_id: null`, `authorization_id: null`, and the **original** payment's `note` and `visibility`. | s4 §Refunds | behaviour |
| R-4-029 | Every payment that is not a refund exposes `refund_of: null`. | s4 §Refunds | behaviour |
| R-4-030 | A refund moves money from the receiver's **available** funds, or fails `409 insufficient_funds`, atomically. | s4 §Refunds | error |
| R-4-031 | A refund never reopens a request or an authorization, and never restores a released hold. | s4 §Refunds | behaviour |
| R-4-032 | A **settlement** payment may be refunded under the ordinary refund rules, and the refund never changes settlement membership. | s4 §Batch | behaviour |
| R-4-033 | **[derived]** Refund error precedence: `401` → body parse `400` → `400 missing_idempotency_key` → key length `422` → idempotency resolution (`200` / `409 idempotency_key_reuse`) → `422 validation_failed` on `amount` → `404 not_found` → `403 forbidden` → `422 invalid_refund_target` → `422 refund_exceeds_payment` → `409 insufficient_funds`. | s4, R-1-075 | error |
| R-4-034 | **[derived]** A refund appears in `GET /activity` by the ordinary visibility rule (R-1-191), using the visibility copied from the original payment, and in both parties' statements as an ordinary money movement with the usual sign convention (R-3-045). | s4 §Refunds, s3 | behaviour |
| R-4-035 | **[derived]** A refund payment has its own revision 1 with `effective_at == recorded_at == created_at` (R-3-060), even though it can never be corrected (R-4-040). | s4, s3 §corrections | behaviour |
| R-4-036 | **[derived]** Several partial refunds of one payment are allowed while their cumulative total stays within the current corrected amount; each is a separate payment with its own `refund_of`. | s4 §Refunds | behaviour |
| R-4-037 | **[derived]** A refund of exactly the full current corrected amount is legal; the next refund of any amount is `422 refund_exceeds_payment`. | s4 §Refunds | behaviour |

## C. Corrections in stage 4

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-040 | Stage-3 corrections remain available for ordinary direct and request payments. **Captures and refund payments cannot themselves be corrected**: `422 linked_payment_immutable`. | s4 §Refunds | error |
| R-4-041 | A correction cannot reduce a payment below its already-refunded amount: `422 refund_exceeds_payment`. | s4 §Refunds | error |
| R-4-042 | Correction debits are checked against **available** funds. | s4 §Refunds | error |
| R-4-043 | **[derived]** A single-payment correction of a settlement member remains `422 linked_payment_immutable` (R-3-075); only `POST /correction-batches` may correct settlement members. | s4 §Batch, s3 | error |

## D. Batch corrections

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-050 | `POST /correction-batches` requires a **settlement operator** and an `Idempotency-Key`, with the same 401/403 rules as settlements: no/unknown token is `401 unauthenticated`, an authenticated non-operator is `403 forbidden`. | s4 §Batch | error |
| R-4-051 | Body is `{"corrections": [{"payment_id","expected_revision","amount","effective_at","reason"}…]}` with 1 to 32 objects having **distinct** `payment_id`s; otherwise `422 validation_failed`. | s4 §Batch | error |
| R-4-052 | Every item carries the ordinary correction fields and the ordinary validation (R-3-063, R-3-064): all five required, `expected_revision` a positive integer, `amount` an integer `0..1000000000`, `reason` a string of 1..200 characters, `effective_at` an RFC 3339 instant not later than now. | s4 §Batch | error |
| R-4-053 | An unknown `payment_id` is `404 not_found`; a stale `expected_revision` is `409 stale_revision`. | s4 §Batch | error |
| R-4-054 | The operator may correct ordinary, request and **settlement** payments; captures and refunds remain immutable (`422 linked_payment_immutable`). | s4 §Batch | error |
| R-4-055 | Correcting **any** settlement member requires including **every** member of that settlement in the same batch, else `422 incomplete_settlement`. | s4 §Batch | error |
| R-4-056 | Members of one settlement must have **identical effective instants** — offset spellings may differ, so compare the instants, not the strings — else `422 validation_failed`. | s4 §Batch | error |
| R-4-057 | Ordinary single-payment corrections remain available for non-members. | s4 §Batch | behaviour |
| R-4-058 | Unknown fields in the batch body and in each item are ignored (R-1-022). | s4 §Batch | behaviour |
| R-4-059 | **Error precedence for a batch, in exactly this order:** (1) item errors in **input order**; (2) settlement completeness (`incomplete_settlement`); (3) resulting **current available** funds (`insufficient_funds`); (4) **historical** total and available funds at every effective/event boundary (`historical_overdraft`). | s4 §Batch | error |
| R-4-060 | Affordability is determined by the **combined effect of all proposed revisions**, not item by item: a batch whose items individually overdraw but jointly do not must succeed, and one that jointly overdraws must fail even if each item alone is affordable. | s4 §Batch | behaviour |
| R-4-061 | Success is `201` with `{"correction_batch_id","recorded_at","revisions":[…]}`, `revisions` in **input order**. | s4 §Batch | behaviour |
| R-4-062 | All new revisions in a batch **share one `recorded_at`**, strictly later than the previous `recorded_at` of **every** member (R-3-003 holds per payment). | s4 §Batch | invariant |
| R-4-063 | Each revision created by a batch exposes `correction_batch_id`. **[derived]** A revision created by a single-payment correction exposes `correction_batch_id: null`. | s4 §Batch | behaviour |
| R-4-064 | Effective times cannot be later than now. | s4 §Batch | error |
| R-4-065 | Original payments and receipts never change; original payment and settlement retries return their original bodies (R-1-112 verbatim rule applies). | s4 §Batch | behaviour |
| R-4-066 | New statements reflect the new revisions, while earlier `snapshot` tokens continue to page their frozen entries. | s4 §Batch | behaviour |
| R-4-067 | A replay returns the original batch response with `200`; a different body with the same key is `409 idempotency_key_reuse`. | s4 §Batch | behaviour |
| R-4-068 | **[derived]** A batch containing two items for the same `payment_id` is `422 validation_failed` under R-4-051's distinctness rule, checked before any lookup. | s4 §Batch | error |
| R-4-069 | **[derived]** A batch of exactly 1 item is legal and behaves like a single correction except that it carries a `correction_batch_id` and may target a settlement member (subject to R-4-055). | s4 §Batch | behaviour |
| R-4-070 | **[derived]** A batch of 33 items is `422 validation_failed`. | s4 §Batch | error |
| R-4-071 | **[derived]** A batch may include members of **several** settlements; completeness (R-4-055) and identical-effective-instant (R-4-056) are evaluated **per settlement**. | s4 §Batch | behaviour |
| R-4-072 | **[derived]** A failed batch claims no idempotency key, so the key remains reusable (R-1-107). | s4 §Batch, §7 | behaviour |

## E. Export and import

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-080 | A stage-4 service accepts, unchanged, exports produced by the team's stage-1, stage-2 **or** stage-3 service, retaining settlement membership, corrections and snapshots. | s4 §Batch | behaviour |
| R-4-081 | **[derived]** A stage-4 export round-trips refunds and their `refund_of` links, correction batches and their `correction_batch_id`s, and every still-valid `snapshot` token, in addition to R-1-205/206, R-2-175 and R-3-124. | s4, §10 | behaviour |
| R-4-082 | **[derived]** A replay of a key claimed under an earlier stage returns that earlier stage's stored body verbatim, with no stage-4 field such as `refund_of` added (R-1-112). | s4, §7, §10 | behaviour |

## F. UI

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-090 | Every stage-2 UI requirement (R-2-090 … R-2-160) continues to hold unchanged: same routes, `data-testid` contract, formatting, responsive and accessibility rules. | s2 §UI | UI |
| R-4-091 | **[derived]** Stage 4 requires no new screen; refunds and batches are API-only. The existing screens must not regress, and a refund — being an ordinary payment — appears in the activity feed with its own `activity-item-{payment_id}` and the visibility copied from its target. | s4 §Refunds | UI |

## G. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-100 | Two concurrent refunds of one payment that together exceed its current corrected amount cannot both succeed; at least one is `422 refund_exceeds_payment` or `409 insufficient_funds`. | s4 §Refunds | invariant |
| R-4-101 | A refund racing a correction of the same payment is serializable; the resulting cumulative refund never exceeds the resulting corrected amount. | s4 §Refunds | invariant |
| R-4-102 | Two concurrent batches sharing any expected payment revision cannot both succeed. | s4 §Batch | invariant |
| R-4-103 | Under a storm of all ten write paths with ~30% replays, R-4-001 … R-4-009 and every stage-1/2/3 invariant hold. | s4, s3, s2 | invariant |
