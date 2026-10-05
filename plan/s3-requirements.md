# Stage 3 requirements — pocketful: statements and payment corrections

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-3.md`.
`§` references are to `stage-1.md` unless prefixed `s2`/`s3`.

**Every requirement in `plan/s1-requirements.md` (R-1-001 … R-1-244) and
`plan/s2-requirements.md` (R-2-001 … R-2-184) continues to apply unchanged in `stage-3/`,
except where a row below explicitly amends one.** Amendments: R-1-100 / R-2-016 (eight
idempotent write paths), R-1-120 / R-2-010 (`GET /me` gains temporal parameters),
R-1-042 (fixture payments may supply `created_at`), R-2-041 (authorizations expose
`closed_at`).

This stage's checks are mostly hidden. Where the spec is silent, the rows marked
**PLANNER DECISION** fix the reading; they are binding on every seat.

## A. Invariants — stage 3 adds five; stages 1–2 still hold

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-001 | The sum of all balances equals the total seeded by the last reset **in every historical view**: at any `as_of`, at any `known_at`, and in any combination of the two. A correction moves money between the same two wallets, so it never changes the system total. | s3 §Corrections | invariant |
| R-3-002 | No balance is negative in any historical view under the latest known revisions: not currently, and not at any past effective-time or event boundary. | s3 §Corrections, §Historical holds | invariant |
| R-3-003 | A revision history is append-only and immutable: an existing revision's `amount`, `effective_at`, `recorded_at` or `reason` never changes, and a revision is never deleted. Revision numbers are consecutive from 1. | s3 §Corrections | invariant |
| R-3-004 | `recorded_at` values for one payment **strictly increase** with revision number. No two revisions of the same payment share a `recorded_at`. | s3 §Corrections | invariant |
| R-3-005 | A snapshot token's result is frozen: the entries, balances, selected revisions, window and default `to` it returns never change, whatever payments, corrections or hold lifecycle events occur after it was issued. | s3 §Stable pagination | invariant |

## B. Payment timestamps and seeded history

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-010 | Every payment's `created_at` is an RFC 3339 instant with an offset identifying when it moved money, and every endpoint that returns a payment includes it. | s3 §Payment timestamps | behaviour |
| R-3-011 | `GET /activity` retains its existing ordering by `created_at`, newest first. | s3 §Payment timestamps | behaviour |
| R-3-012 | A seeded payment may supply `created_at`; omitting it uses reset time, which orders before every subsequently API-created payment. | s3 §Payment timestamps | behaviour |
| R-3-013 | A seeded `created_at` in the future is `422 validation_failed` from `POST /_test/reset`, with no state change. | s3 §Payment timestamps | error |
| R-3-014 | A fixture's `balance` remains the balance **after** all seeded payments; loading them must not change it. | s3 §Payment timestamps | behaviour |
| R-3-015 | A payment's revision 1 has the originally paid `amount` and `effective_at = recorded_at = created_at`. For a seeded payment, the supplied (or reset-time) `created_at` is also its original recorded and effective time. | s3 §Corrections | behaviour |
| R-3-016 | A wallet's **opening balance** equals its seeded ending balance minus the net effect of the original seeded payments. Corrections never change opening balances. | s3 §Corrections | invariant |
| R-3-017 | An account created after reset opens at zero. | s3 §Corrections | behaviour |
| R-3-018 | Seeded history is consistent and nonnegative; a fixture whose seeded payments imply a negative balance at any point is `422 validation_failed` from reset, changing nothing. | s3 §Corrections | error |
| R-3-018a | **PLANNER DECISION (tie-break, 2026-10-05).** "At any point" in R-3-018 **includes the opening instant itself**, before any seeded payment is replayed. A user's bare opening balance — seeded ending balance minus the net effect of the original seeded payments — must be `>= 0` on its own. A fixture seeding a receiver with ending balance `0` and a received payment of `1000` implies an opening balance of `-1000` and is therefore `422 validation_failed` from reset. **Decisive reason:** spec line 38 requires `GET /me?as_of=<before the earliest payment>` to return that opening balance, so accepting such a fixture would force the service to *report* a negative balance, violating R-3-002 and R-1-002 ("no balance is ever negative"). No service can satisfy R-3-024 and R-3-002 simultaneously unless the fixture is rejected at reset. The forward-replay-between-payments check is necessary but **not sufficient**. | s3 §Corrections line 86–87, line 38 | error |
| R-3-018b | **PLANNER DECISION.** The same check applies to `POST /_test/import`: an imported state implying a negative balance at any instant, including the opening instant, is `422 validation_failed` with the destination unchanged (R-1-045, R-3-207). The check lives where both the reset and import paths reach it, so the two cannot drift. | s3 §Corrections, §10 | error |
| R-3-019 | **PLANNER DECISION.** Two seeded payments may share a `created_at`. Ties are broken by payment `id` ascending wherever an order is required (R-3-030, R-3-061), so a seeded tie is deterministic rather than unspecified. This narrows R-1-195, which leaves same-second feed order unspecified: `GET /activity` keeps that latitude, statements do not. | s3 §Statement, §4 | behaviour |

## C. `GET /me` as of an instant

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-020 | `as_of` is optional on `GET /me` and is an RFC 3339 instant **with an offset**. A naive local time, a bare date, an empty value or any other form is `422 validation_failed`. | s3 §GET /me | error |
| R-3-021 | Without any temporal query parameter, `GET /me` retains its existing money fields and reports **current corrected** values. | s3 §GET /me | behaviour |
| R-3-022 | With `as_of`, `balance` is the caller's balance as it stood at that instant: after every payment of theirs with `created_at` (selected `effective_at`, once corrections exist) at or before `as_of`, and before every payment after it. | s3 §GET /me | behaviour |
| R-3-023 | A payment made at exactly `as_of` counts as having happened — the boundary is inclusive. | s3 §GET /me | behaviour |
| R-3-024 | An `as_of` at or after the latest payment returns the current balance; an `as_of` before the earliest returns the opening balance (R-3-016). | s3 §GET /me | behaviour |
| R-3-025 | The response carries `as_of` back **exactly as given**, byte for byte, including the offset spelling. | s3 §GET /me | behaviour |
| R-3-026 | `as_of` may be in the future. | s3 §Corrections | behaviour |
| R-3-027 | **PLANNER DECISION.** `as_of` and `known_at` are independent and may be combined freely; neither implies the other. With both, select revisions by `known_at` (R-3-050) and then apply them by effective time against `as_of`. | s3 §Corrections | behaviour |

## D. `GET /statement`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-030 | `GET /statement?from=&to=&limit=&offset=` returns the payments the caller **sent or received** in the half-open window `[from, to)`, **oldest first**, each with the caller's balance immediately after it. | s3 §Statement | behaviour |
| R-3-031 | `from` is optional and defaults to the opening of the wallet; `to` is optional and defaults to now. `limit` and `offset` behave exactly as on `GET /requests` (R-1-073, R-1-074, R-1-166, R-1-167). | s3 §Statement | behaviour |
| R-3-032 | The response is `{"opening_balance", "entries": [{"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"}], "closing_balance", "has_more", "snapshot"}`. | s3 §Statement, §Stable pagination | behaviour |
| R-3-033 | Entries are ordered by selected `effective_at` ascending, then payment `id` ascending for ties. | s3 §Corrections, §Statement | behaviour |
| R-3-034 | `opening_balance` is the balance immediately before `from`; `closing_balance` is the balance immediately before `to`. | s3 §Statement | behaviour |
| R-3-035 | `opening_balance` plus every `delta` in the **full** window equals `closing_balance`. A sent payment has a negative `delta`, a received payment a positive one. | s3 §Statement | invariant |
| R-3-036 | Pagination changes neither an entry's `balance_after` nor the window's opening and closing balances: those describe the full window regardless of `limit` and `offset`. | s3 §Statement | invariant |
| R-3-037 | Only payments the caller sent or received appear, **including when other payments are public**. The activity-feed visibility rules do not apply to statements. | s3 §Statement | behaviour |
| R-3-038 | `payment.amount` in an entry is the **selected** amount for that statement, not necessarily the original. | s3 §Corrections | behaviour |
| R-3-039 | A zero-amount revision still appears as an entry, with `delta` zero. | s3 §Corrections | behaviour |
| R-3-040 | A correction is never counted alongside the revision it replaces: exactly one revision per payment contributes to any one statement. | s3 §Corrections | invariant |
| R-3-041 | With no corrections and no `known_at`, statement behaviour is exactly as it would have been without this stage's revision machinery. | s3 §Corrections | behaviour |
| R-3-042 | A statement contains **money movements only**: authorization, release and expiry are not payments and never appear. A capture appears exactly once, with its `authorization_id` link. | s3 §Historical holds | behaviour |
| R-3-043 | **PLANNER DECISION.** `from` later than `to` yields an empty window: zero entries, `opening_balance == closing_balance`, `has_more: false`. It is not an error — the spec states no ordering constraint, and the half-open window `[from, to)` is empty by construction. | s3 §Statement | behaviour |
| R-3-044 | **PLANNER DECISION.** `from` and `to` follow `as_of`'s format rule (R-3-020): RFC 3339 with an offset, else `422 validation_failed`. The window is half-open, so a payment at exactly `from` is included and one at exactly `to` is excluded. | s3 §Statement, §GET /me | behaviour |

## E. Corrections

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-050 | `POST /payments/{payment_id}/corrections` requires an `Idempotency-Key` and the **original sender**. It is the eighth idempotent write path. | s3 §Corrections | behaviour |
| R-3-051 | An authenticated non-sender is `403 forbidden`; an unknown payment is `404 not_found`; no token is `401 unauthenticated`. | s3 §Corrections | error |
| R-3-052 | The body is `{"expected_revision", "amount", "effective_at", "reason"}` and **all four fields are required**; omitting any is `422 validation_failed`. | s3 §Corrections | error |
| R-3-053 | `expected_revision` is a positive integer; `amount` is an integer `0..1000000000` (zero reverses the entire payment); `reason` is a string of 1..200 characters; `effective_at` is an RFC 3339 instant **not later than now**. Any violation is `422 validation_failed`. | s3 §Corrections | error |
| R-3-054 | A correction changes neither the parties nor the visibility of the payment. | s3 §Corrections | behaviour |
| R-3-055 | Success appends an immutable revision and returns `201` with `{"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"}`, `recorded_at` server-assigned. | s3 §Corrections | behaviour |
| R-3-056 | An `expected_revision` that is not the payment's current latest revision is `409 stale_revision`, changing nothing. | s3 §Corrections | error |
| R-3-057 | A successful replay returns `200` with **that original revision**, even after newer revisions exist; the same key with a different body is `409 idempotency_key_reuse`. | s3 §Corrections | behaviour |
| R-3-058 | The difference from the previous amount moves between the **same two wallets** in the same atomic step: increasing the amount debits the original sender, decreasing it debits the original receiver. | s3 §Corrections | behaviour |
| R-3-059 | A currently unaffordable debit is `409 insufficient_funds`. **Current unaffordability takes precedence over historical overdraft.** | s3 §Corrections, §Historical holds | error |
| R-3-060 | Otherwise, if any user's corrected balance would be negative at **any** effective-time boundary, the correction is `409 historical_overdraft`. Balances at a boundary include the combined effect of all movements at that instant. | s3 §Corrections | error |
| R-3-061 | Either failure preserves balances, revision history, statements and idempotency state exactly; a rejected correction claims no key. | s3 §Corrections | invariant |
| R-3-062 | The original payment and every original idempotent response remain unchanged; `GET /activity` continues to display the original payment, and correction records are never new feed payments. | s3 §Corrections | behaviour |
| R-3-063 | `GET /payments/{payment_id}/revisions` returns `{"revisions": [...]}` in revision order, **including revision 1** with `reason: ""`. | s3 §Corrections | behaviour |
| R-3-064 | Only the two parties may read the revisions of a payment; a third party gets `404 not_found` **even for a public payment**; no token is `401 unauthenticated`. | s3 §Corrections | error |
| R-3-065 | A correction of a **settlement member** is `422 linked_payment_immutable`. | s3 §Settlement history | error |
| R-3-066 | A correction of a **capture** is `422 linked_payment_immutable`. | s3 §Settlement history | error |
| R-3-067 | Concurrent corrections using the same `expected_revision` cannot both succeed: exactly one returns `201`, the other `409 stale_revision`. | s3 §Stable pagination | invariant |
| R-3-068 | **PLANNER DECISION.** Correction error precedence, extending R-1-075: `401` → `404 not_found` (unknown payment) → `403 forbidden` (non-sender) → `400 missing_idempotency_key` → idempotency resolution → `422 validation_failed` (field rules) → `422 linked_payment_immutable` → `409 stale_revision` → `409 insufficient_funds` → `409 historical_overdraft`. Immutability precedes staleness because a capture or settlement member can never be corrected at any revision. | s3 §Corrections, §5 | error |
| R-3-069 | **PLANNER DECISION.** A correction whose `amount` equals the current amount is valid, not a no-op error: it appends a revision with a zero movement. R-3-003 and R-3-004 still apply. | s3 §Corrections | behaviour |

## F. `known_at` and revision selection

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-070 | `GET /me` and `GET /statement` accept an optional `known_at`, an RFC 3339 instant with an offset. | s3 §Corrections | behaviour |
| R-3-071 | For each payment, select its **latest revision recorded at or before `known_at`**; if none was recorded by then, that payment contributes **nothing** to the view. | s3 §Corrections | behaviour |
| R-3-072 | Omitting `known_at` means everything known when the read begins. | s3 §Corrections | behaviour |
| R-3-073 | Selected revisions are then applied according to their **effective** times; `as_of` keeps its inclusive meaning and a statement keeps its half-open window. | s3 §Corrections | behaviour |
| R-3-074 | Both query instants may be in the future. | s3 §Corrections | behaviour |
| R-3-075 | An invalid or empty `known_at` is `422 validation_failed`, by the same rule as `as_of` (R-3-020). | s3 §Corrections | error |
| R-3-076 | A supplied `known_at` is echoed back **exactly as given**. | s3 §Corrections | behaviour |
| R-3-077 | A `known_at` earlier than a payment's original `recorded_at` excludes that payment entirely from the view — it is not merely reduced to zero. | s3 §Corrections | behaviour |
| R-3-078 | **PLANNER DECISION.** Exactly two endpoints accept temporal parameters: `GET /me` (`as_of`, `known_at`) and `GET /statement` (`from`, `to`, `known_at`). `GET /payments/{id}/revisions` accepts **none**. A `known_at` or `as_of` on it is an unknown query parameter and is therefore **ignored** under R-1-023, returning the complete revision list unchanged. It is never `404` for a temporal reason — `404` on that endpoint means only unknown payment or non-party (R-3-064). Rationale: R-3-070 names the two endpoints that gain `known_at`, and the revisions endpoint is a record of what was recorded, so filtering it by recording time would hide the very history it exists to expose. | s3 §Corrections, §4 | behaviour |
| R-3-079 | **PLANNER DECISION.** The statement pagination token is spelled exactly `snapshot` — both as the response field (R-3-032) and as the request query parameter (R-3-082, R-3-083). Not `snapshot_token`, not `snapshotToken`. The spec's wording ("returns an opaque `snapshot` token", `GET /statement?snapshot=<token>`) names the field, not merely the concept. | s3 §Stable pagination | behaviour |

## G. Stable statement pagination

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-080 | Every **first** `GET /statement` response returns an opaque `snapshot` token. | s3 §Stable pagination | behaviour |
| R-3-081 | The token freezes the caller's selected revisions, window, balances, entries and default `to` as at that read. | s3 §Stable pagination | behaviour |
| R-3-082 | `GET /statement?snapshot=<token>&limit=&offset=` pages that exact frozen result, even after later payments or corrections. | s3 §Stable pagination | behaviour |
| R-3-083 | Only `limit` and `offset` may accompany a snapshot; supplying `from`, `to` or `known_at` with it is `422 validation_failed`. | s3 §Stable pagination | error |
| R-3-084 | An unknown token, another user's token, or a token issued before the last reset is `404 not_found`. | s3 §Stable pagination | error |
| R-3-085 | Tokens last until reset; no survival across a container restart is required. | s3 §Stable pagination | behaviour |
| R-3-086 | Paging a snapshot changes neither balances nor entries; the final partial page and offsets beyond the end report `has_more` correctly. | s3 §Stable pagination | behaviour |
| R-3-087 | Unrecognized query parameters remain ignored under R-1-023. | s3 §Stable pagination | behaviour |
| R-3-088 | A correction may move a payment **into or out of** a statement window; existing snapshots remain unchanged by concurrent payments or corrections. | s3 §Stable pagination | invariant |
| R-3-089 | Old snapshots remain unchanged after **any** hold lifecycle action or correction. | s3 §Historical holds | invariant |
| R-3-090 | **PLANNER DECISION.** A snapshot-paged response echoes the same `snapshot` token it was given, so a caller can page without retaining the first response. Returning a *new* token per page would contradict R-3-081's freeze. | s3 §Stable pagination | behaviour |
| R-3-091 | **PLANNER DECISION.** A token is bound to the user who requested it; `404 not_found` for anyone else (R-3-084) takes precedence over any validation of the accompanying `limit`/`offset`, so a token is never confirmed to exist by a differing error. | s3 §Stable pagination, §5 | error |

## H. Settlement and capture history

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-100 | Stage-1 settlements retain their original receipts and privacy rules. | s3 §Settlement history | behaviour |
| R-3-101 | Each settlement member's original revision uses the shared `committed_at` as both `effective_at` and `recorded_at`. | s3 §Settlement history | behaviour |
| R-3-102 | A stage-3 service accepts, unchanged, exports produced by the team's stage-1 **or** stage-2 service, and the ledger imports and accounts for authorizations and captures. | s3 §Settlement history | behaviour |
| R-3-103 | A capture is an immutable linked payment, appears in a statement exactly once with its `authorization_id`, and carries a revision 1 like any other payment. | s3 §Settlement history, §Historical holds | behaviour |

## I. Historical holds

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-110 | For `GET /me?as_of=T&known_at=K` all four money fields describe that same view: `balance = total` and `available = total − held`. | s3 §Historical holds | behaviour |
| R-3-111 | A hold starts at authorization creation; a **nonfinal** capture reduces it at capture time; a final capture, a void or expiry releases the remainder at that event's time. | s3 §Historical holds | behaviour |
| R-3-112 | Expiry takes effect at `expires_at`. Events other than clock expiry are known at their server-assigned event time. | s3 §Historical holds | behaviour |
| R-3-113 | Once an authorization's creation is known, its expiry deadline is known too — expiry needs no separate recorded event to be visible at a `known_at` after creation. | s3 §Historical holds | behaviour |
| R-3-114 | For a query beyond now, an open hold expires at its deadline. | s3 §Historical holds | behaviour |
| R-3-115 | Without `as_of`, the view uses the instant the request began. | s3 §Historical holds | behaviour |
| R-3-116 | Every authorization response exposes `closed_at`: null while open, the event time when closed. | s3 §Historical holds | behaviour |
| R-3-117 | Historical `total` follows the stage-3 effective/recorded-time rules. | s3 §Historical holds | behaviour |
| R-3-118 | A correction is `409 historical_overdraft` if it makes **either** `total` **or** `available` negative at any past effective or event boundary, under the latest known revisions. | s3 §Historical holds | error |
| R-3-119 | Seeded **open** holds are assumed created at reset unless `created_at` is supplied; seeded **closed** holds need not reconstruct a prior lifecycle. | s3 §Historical holds | behaviour |
| R-3-120 | **PLANNER DECISION.** The fixture's `authorizations` entries accept an optional `created_at` (R-3-119). A seeded `created_at` later than reset time, or later than the authorization's own `expires_at`, is `422 validation_failed` from reset — the same shape as R-3-013. | s3 §Historical holds | error |

## J. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-130 | Concurrent requests remain serializable and every requirement above holds at every read. | s2 §Concurrent operations | invariant |
| R-3-131 | A storm of mixed payments, request payments, splits, settlements, authorizations, captures, voids and **corrections** with ~30% replays preserves R-3-001 … R-3-005, R-2-001 … R-2-005 and R-1-001 … R-1-007. | s3, s2 | invariant |
| R-3-132 | A snapshot read concurrent with corrections returns a self-consistent frozen result, never a torn mix (R-3-005, R-3-088). | s3 §Stable pagination | invariant |
| R-3-133 | A correction racing a payment between the same two wallets cannot drive either balance negative at any boundary. | s3 §Corrections | invariant |
