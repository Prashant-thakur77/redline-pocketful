# Stage 4 requirements — pocketful: refunds and batch corrections

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-4.md`.
`§` references are to `stage-1.md` unless prefixed `s2`/`s3`/`s4`.

**Every requirement in `plan/s1-requirements.md` (R-1-001 … R-1-244),
`plan/s2-requirements.md` (R-2-001 … R-2-184) and `plan/s3-requirements.md`
(R-3-001 … R-3-164) continues to apply unchanged in `stage-4/`,** except where a row below
explicitly amends one. Amendments: R-1-131/R-2-018 (the payment object gains `refund_of`),
R-1-100/R-2-016/R-3-060 (**ten** idempotent write paths), R-3-123 (captures and refunds are
not correctable), R-3-069 (correction debits checked against `available`).

**There are exactly ten idempotent write paths:** stage 1's five (`POST /payments`,
`POST /requests`, `POST /requests/{id}/pay`, `POST /splits`, `POST /settlements`), stage 2's
two (`POST /authorizations`, `POST /authorizations/{id}/capture`), stage 3's one
(`POST /payments/{id}/corrections`), and stage 4's two (`POST /payments/{id}/refunds`,
`POST /correction-batches`).

## A. Invariants — stage 4 adds five; the earlier eighteen still hold

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-001 | A refund moves **existing** money and never creates or destroys any: the sum of all balances still equals the total seeded by the last reset, in every historical view, with refunds present. | s4 §Refunds | invariant |
| R-4-002 | Cumulative refunds against one payment never exceed that payment's **current corrected** amount, under concurrency and replays. | s4 §Refunds | invariant |
| R-4-003 | A refund payment is terminal: it can never itself be refunded and never corrected. A capture is likewise never correctable. | s4 §Refunds | invariant |
| R-4-004 | A correction batch is all-or-nothing: either every proposed revision commits together or none does, and a rejected batch leaves history, balances and idempotency records byte-identical. | s4 §Batch corrections | invariant |
| R-4-005 | Original payments, original receipts and earlier snapshot tokens are never changed by a refund or a batch correction: a saved statement pages its frozen entries forever. | s4 §Batch corrections, s3 §Stable pagination | invariant |

## B. `POST /payments/{payment_id}/refunds`

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-010 | `POST /payments/{payment_id}/refunds` with body `{"amount": <int>}` requires `Idempotency-Key`; it is the ninth idempotent write path and all of §7 applies. | s4 §Refunds | behaviour |
| R-4-011 | Only the **original receiver** may refund; any other authenticated caller is `403 forbidden`. An unknown payment is `404 not_found`. No token is `401 unauthenticated`. | s4 §Refunds | error |
| R-4-012 | The target may be a direct payment, a request payment or a **capture**, but never a refund. | s4 §Refunds | behaviour |
| R-4-013 | Refunding a refund is `422 invalid_refund_target`. | s4 §Refunds | error |
| R-4-014 | An invalid `amount` is `422 validation_failed`. **Decision:** valid means a number with an integral value, at least `1` and at most `1000000000`; a boolean, string, `null`, zero, negative or non-integral value is `422 validation_failed` (R-1-069, R-1-032, R-1-033). | s4 §Refunds | error |
| R-4-015 | Cumulative refunds may not exceed the payment's **current corrected** amount: a refund that would exceed it is `422 refund_exceeds_payment`. | s4 §Refunds | error |
| R-4-016 | A refund is a **new payment in the opposite direction** — from the original receiver to the original sender — carrying `refund_of` naming the target, `request_id: null`, `authorization_id: null`, and the **original** payment's `note` and `visibility`. | s4 §Refunds | behaviour |
| R-4-017 | Success is `201` with that payment; a replay returns `200` with the original body. | s4 §Refunds | behaviour |
| R-4-018 | A refund moves existing money from the **refunding party's `available`** funds, atomically, or fails `409 insufficient_funds` and changes nothing. | s4 §Refunds | error |
| R-4-019 | A refund never reopens a request or an authorization and never restores a released hold. | s4 §Refunds | behaviour |
| R-4-020 | Every payment that is not a refund exposes `refund_of: null`. | s4 §Refunds | behaviour |
| R-4-021 | **Decision.** Refund precedence, extending R-1-075: `401` → `400 malformed_request` → `400 missing_idempotency_key` → `422` over-long key → idempotency resolution (`200` replay / `409 idempotency_key_reuse`) → `404 not_found` (unknown payment) → `403 forbidden` (not the receiver) → `422 validation_failed` (`amount` rules) → `422 invalid_refund_target` (target is a refund) → `422 refund_exceeds_payment` → `409 insufficient_funds`. `404` precedes `403` as in R-3-073. | §5, s4 §Refunds | error |
| R-4-022 | **Decision.** A refund is an ordinary payment for every read: it appears in `GET /activity` by the ordinary visibility rule (R-1-191, inheriting the original's `visibility`), appears in both parties' statements with the appropriate `delta` sign, and has a revision 1 readable through `GET /payments/{id}/revisions` — but no correction may ever be appended to it (R-4-030). | s4 §Refunds, s3 | behaviour |
| R-4-023 | **Decision.** Refunding is not restricted to a window and does not require the original payment to be uncorrected: the only cumulative limit is R-4-015 against the current corrected amount. | s4 §Refunds | behaviour |
| R-4-024 | **Decision.** `refund_of` names the **immediate** target payment id, and because refunds of refunds are forbidden (R-4-013) no chain of `refund_of` longer than one link can exist. | s4 §Refunds | behaviour |

## C. Corrections after refunds exist

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-030 | A correction of a **capture** or of a **refund** payment is `422 linked_payment_immutable`. | s4 §Refunds | error |
| R-4-031 | Stage-3 single-payment corrections remain available for ordinary direct and request payments. | s4 §Refunds | behaviour |
| R-4-032 | A correction may not reduce a payment below its already-refunded cumulative amount: `422 refund_exceeds_payment`. | s4 §Refunds | error |
| R-4-033 | Correction **debits** are checked against `available` funds, not `total` (amending R-3-069 to say so explicitly for stage 4). | s4 §Refunds | behaviour |
| R-4-034 | **Decision.** R-4-032 is evaluated within the correction precedence ladder of R-3-073, immediately after `linked_payment_immutable` and before `stale_revision`, since it is a property of the proposed amount rather than of concurrency. | s4 §Refunds, s3 §Corrections | error |

## D. `POST /correction-batches`

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-040 | `POST /correction-batches` requires a **settlement operator** and an `Idempotency-Key`, with the same `401`/`403` rules as `POST /settlements` (R-1-221): no or unknown token is `401 unauthenticated`, an authenticated non-operator is `403 forbidden`. It is the tenth idempotent write path. | s4 §Batch corrections | behaviour |
| R-4-041 | Body is `{"corrections": [ { "payment_id", "expected_revision", "amount", "effective_at", "reason" } … ] }` with **1 to 32** objects having **distinct** `payment_id`s; a count outside that range, a non-array, an absent key or a duplicate `payment_id` is `422 validation_failed`. | s4 §Batch corrections | error |
| R-4-042 | Every item carries the ordinary correction fields and the ordinary per-field validation of R-3-062/R-3-063. | s4 §Batch corrections | error |
| R-4-043 | An unknown `payment_id` is `404 not_found`; a stale `expected_revision` is `409 stale_revision`. | s4 §Batch corrections | error |
| R-4-044 | The operator may correct ordinary, request and **settlement member** payments; captures and refunds remain immutable (`422 linked_payment_immutable`). | s4 §Batch corrections | behaviour |
| R-4-045 | Correcting any settlement member requires including **every** member of that settlement in the same batch, else `422 incomplete_settlement`. | s4 §Batch corrections | error |
| R-4-046 | Members of one settlement must have **identical effective instants** — offset spellings may differ, so comparison is by instant, not by string — else `422 validation_failed`. | s4 §Batch corrections | error |
| R-4-047 | Ordinary single-payment corrections remain available for payments that are not settlement members. | s4 §Batch corrections | behaviour |
| R-4-048 | Unknown fields in the batch body and in each item are ignored (R-1-022). | s4 §Batch corrections | behaviour |
| R-4-049 | Error precedence within the batch is: **item errors in input order** → settlement completeness (`incomplete_settlement`) → resulting **current** available funds (`insufficient_funds`) → **historical** total and available funds at every effective/event boundary (`historical_overdraft`). The existing codes apply throughout: `linked_payment_immutable`, `refund_exceeds_payment`, `insufficient_funds`, `historical_overdraft`. | s4 §Batch corrections | error |
| R-4-050 | Affordability is determined by the **combined** effect of all proposed revisions, not by each in isolation: a batch whose items individually overdraw but jointly net to an affordable position must succeed, and one that jointly overdraws must fail even if each item alone is affordable. | s4 §Batch corrections | behaviour |
| R-4-051 | A rejected batch leaves history, balances and idempotency records unchanged, and claims no idempotency key (R-1-107). | s4 §Batch corrections | behaviour |
| R-4-052 | Success is `201` with `{"correction_batch_id", "recorded_at", "revisions": [ … ] }`, `revisions` in **input order**. | s4 §Batch corrections | behaviour |
| R-4-053 | All new revisions share one `recorded_at`, **strictly later** than the previous `recorded_at` of every member (preserving R-3-003's strict monotonicity per payment). | s4 §Batch corrections | invariant |
| R-4-054 | Each revision created by a batch also exposes `correction_batch_id`. **Decision:** a revision created by a single-payment correction, and revision 1 of any payment, expose `correction_batch_id: null`. | s4 §Batch corrections | behaviour |
| R-4-055 | Effective times in a batch cannot be later than now (R-3-063, R-3-074). | s4 §Batch corrections | error |
| R-4-056 | Original payments and receipts never change; original payment retries and original **settlement** retries still return their original bodies. | s4 §Batch corrections | invariant |
| R-4-057 | New statements reflect the new revisions, while **earlier snapshot tokens continue to page their frozen entries** (R-3-005, R-3-108). | s4 §Batch corrections | invariant |
| R-4-058 | A batch replay returns `200` with the original complete batch response and changes nothing. | s4 §Batch corrections | behaviour |
| R-4-059 | **Decision.** A batch containing two or more members of the **same** settlement satisfies R-4-045 only if it contains *all* of that settlement's members; a batch may legitimately span several settlements, and completeness is evaluated per settlement. | s4 §Batch corrections | behaviour |
| R-4-060 | **Decision.** `incomplete_settlement` is evaluated after **all** item-level errors in input order (R-4-049), so a batch that is both incomplete and contains an invalid item returns the item's error, not `incomplete_settlement`. | s4 §Batch corrections | error |

## E. Settlements and refunds together

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-070 | A settlement member payment **may** be refunded under the ordinary refund rules of section B. | s4 | behaviour |
| R-4-071 | A refund never changes settlement membership: the original member keeps its `settlement_id`, and the refund payment is not a member of that settlement (`settlement_id: null`). | s4 | behaviour |
| R-4-072 | Stage-1 settlement receipts and privacy rules continue to apply unchanged (R-3-120). | s4, s3 §Settlement history | behaviour |

## F. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-080 | Concurrent corrections sharing **any** expected payment revision cannot both succeed — including a single correction racing a batch, and two batches overlapping on one payment. Exactly one commits; the other is `409 stale_revision`. | s4 | invariant |
| R-4-081 | Two concurrent refunds of the same payment that together exceed its current corrected amount cannot both succeed: at least one is `422 refund_exceeds_payment`, and money moves at most once per key. | s4 §Refunds | invariant |
| R-4-082 | A refund racing a correction of the same payment remains serializable, and R-4-002 and R-4-032 hold at every read. | s4 | invariant |
| R-4-083 | Under a storm of mixed payments, request payments, splits, settlements, authorizations, captures, voids, corrections, refunds and correction batches with ~30% replays, every invariant in section A and in stages 1 through 3 holds. | s4, §1 | invariant |

## G. Upgrade from stages 1, 2 and 3

| id | requirement | spec | kind |
|---|---|---|---|
| R-4-090 | A stage-4 service accepts, unchanged, an export produced by the team's **stage-1, stage-2 or stage-3** service, returning `204`. | s4 | behaviour |
| R-4-091 | Such an import retains settlement membership, corrections and snapshots, in addition to everything R-1-205/R-1-206/R-2-175/R-3-133 require. | s4 | behaviour |
| R-4-092 | **Decision.** An imported payment with no `refund_of` field is treated as `refund_of: null` and is refundable under section B; nothing about the upgrade makes previously existing payments terminal. | s4, §10 | behaviour |
| R-4-093 | A stage-4 export round-trips `refund_of`, `correction_batch_id` on every revision, and cumulative refunded amounts per payment. | s4, §10 | behaviour |
