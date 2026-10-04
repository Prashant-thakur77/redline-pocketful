# Stage 3 requirements — pocketful: statements and payment corrections

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-3.md`.
`§` references are to `stage-1.md` unless prefixed `s2`/`s3`.

**Every requirement in `plan/s1-requirements.md` (R-1-001 … R-1-244) and
`plan/s2-requirements.md` (R-2-001 … R-2-184) continues to apply unchanged in `stage-3/`,
except where a row below explicitly amends one.** Amendments: R-1-120/R-2-010 (`GET /me`
gains `as_of`/`known_at`), R-1-131/R-2-018 (the payment object gains `refund_of`-less
revision fields), R-1-100/R-2-016 (eight idempotent write paths), R-1-042 (fixture payments
may supply `created_at`), R-2-041 (authorizations expose `closed_at`).

This is the stage where the service stops being a current-state machine. Two independent time
axes arrive — **effective** (when money took effect) and **recorded** (when the service learned
it) — and almost nothing about their interaction appears in an example. Sections E through M
are therefore where the test effort belongs.

## A. Invariants — stage 3 adds six; stages 1 and 2's twelve still hold

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-001 | The sum of all balances equals the total seeded by the last reset (or import) **in every historical view**: for any `as_of` and any `known_at`, including instants in the future and before the earliest payment. A correction moves money between two wallets and never creates or destroys any. | s3 §Corrections | invariant |
| R-3-002 | No user's balance is negative at **any** effective-time boundary under the latest known revisions; a correction that would make one so is refused. Balances at a boundary include the combined effect of all movements at that instant. | s3 §Corrections | invariant |
| R-3-003 | A revision history is **append-only and immutable**: no existing revision's `amount`, `effective_at`, `recorded_at` or `reason` ever changes, revision numbers are consecutive from 1, and `recorded_at` values for one payment **strictly** increase. | s3 §Corrections | invariant |
| R-3-004 | The original payment, every original receipt and every original idempotent response remain byte-identical forever: a correction never rewrites what a caller was already told. | s3 §Corrections | invariant |
| R-3-005 | A snapshot token's result is frozen at the read that issued it: its selected revisions, window, balances, entries and default `to` never change afterwards, under any later payment, correction, capture, void or expiry. | s3 §Stable pagination | invariant |
| R-3-006 | Opening balances — seeded ending balances minus the net effect of the original seeded payments — are invariant under every correction. New accounts open at zero. | s3 §Corrections | invariant |

## B. Payment timestamps

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-010 | Every payment's `created_at` is an RFC 3339 instant with an offset identifying when it moved money, and **every** endpoint that returns a payment includes it. | s3 §Payment timestamps | behaviour |
| R-3-011 | `GET /activity` keeps its existing ordering by `created_at`, newest first, and keeps showing the **original** payment amount; correction records are not new feed items. | s3 §Payment timestamps, §Corrections | behaviour |
| R-3-012 | A seeded payment may supply `created_at`; omitting it uses reset time, which orders before every subsequently API-created payment. | s3 §Payment timestamps | behaviour |
| R-3-013 | A seeded `created_at` later than now makes `POST /_test/reset` return `422 validation_failed` with no state change. | s3 §Payment timestamps | error |
| R-3-014 | A fixture's `balance` remains the balance **after** all seeded payments (R-1-043); loading seeded payments, now that they carry times and revisions, still does not change it. | s3 §Payment timestamps | behaviour |
| R-3-015 | Seeded history is consistent and nonnegative: a fixture whose seeded payments imply a negative balance at any point is `422 validation_failed` from reset. | s3 §Corrections | error |
| R-3-016 | **Decision.** A seeded `created_at` that is not a valid RFC 3339 instant with an explicit offset is `422 validation_failed` from reset, by R-1-068. Two seeded payments may share a `created_at`; ties order by payment id ascending (R-3-030). | §5, s3 §Statement | error |

## C. `GET /me?as_of=…`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-020 | `as_of` is optional and must be an RFC 3339 instant **with an offset**. A naive local time, a bare date, an empty value or any other form is `422 validation_failed`. | s3 §GET /me | error |
| R-3-021 | Without any temporal query parameter, `GET /me` retains its existing money fields and reports **current corrected** values. | s3 §GET /me | behaviour |
| R-3-022 | With `as_of`, `balance` is the caller's balance as it stood at that instant: after every payment of theirs with `created_at` (selected `effective_at`, per R-3-050) at or before `as_of`, and before every one after it. | s3 §GET /me | behaviour |
| R-3-023 | `as_of` is **inclusive**: a payment made at exactly `as_of` counts as having happened. | s3 §GET /me | behaviour |
| R-3-024 | An `as_of` at or after the latest payment returns the current balance; an `as_of` before the earliest returns the opening balance — what the wallet held before anything moved. | s3 §GET /me | behaviour |
| R-3-025 | The response carries `as_of` back **exactly as given**, including its original offset spelling. | s3 §GET /me | behaviour |
| R-3-026 | `as_of` may be in the future (R-3-073). | s3 §Corrections | behaviour |

## D. `GET /statement`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-030 | `GET /statement` returns the payments the caller sent or received in the half-open window `[from, to)`, **oldest first**, ordered by selected `effective_at` ascending then payment `id` ascending for ties. | s3 §Statement, §Corrections | behaviour |
| R-3-031 | `from` and `to` are both optional: `from` defaults to the opening of the wallet and `to` to now. Both are RFC 3339 instants with an offset; any other form is `422 validation_failed`. | s3 §Statement | error |
| R-3-032 | The response is `{"opening_balance", "entries": [...], "closing_balance", "has_more", "snapshot"}`; each entry is `{"payment", "delta", "balance_after", "revision", "effective_at", "recorded_at"}`. | s3 §Statement, §Corrections | behaviour |
| R-3-033 | `opening_balance` is the caller's balance immediately **before** `from`; `closing_balance` is the balance immediately **before** `to`. | s3 §Statement | behaviour |
| R-3-034 | `opening_balance` plus every `delta` in the **full** window equals `closing_balance`. A sent payment has a negative `delta`; a received payment has a positive one. | s3 §Statement | invariant |
| R-3-035 | Pagination never changes an entry's `balance_after`, nor the window's opening and closing balances: those describe the full window regardless of `limit` and `offset`. | s3 §Statement | invariant |
| R-3-036 | `limit` and `offset` behave exactly as on `GET /requests` (R-1-073, R-1-074, R-1-166, R-1-167), and `has_more` is correct on the final partial page and for offsets beyond the end. | s3 §Statement, §Stable pagination | behaviour |
| R-3-037 | Only payments the caller sent or received appear in their statement — **including when other payments are public**. The activity-feed visibility rules do not apply to statements. | s3 §Statement | behaviour |
| R-3-038 | `balance_after` is the caller's balance immediately after that entry, computed over the full ordered window from `opening_balance`. | s3 §Statement | behaviour |
| R-3-039 | `payment.amount` in an entry is the **selected** amount for this statement, not necessarily the original. | s3 §Corrections | behaviour |
| R-3-040 | A zero-amount revision still appears as an entry, with `delta: 0`. | s3 §Corrections | behaviour |
| R-3-041 | A correction is never counted alongside the revision it replaces: exactly one revision per payment contributes to any one view. | s3 §Corrections | invariant |
| R-3-042 | With no corrections and no `known_at`, `GET /statement` behaves exactly as this section's pre-correction description. | s3 §Corrections | behaviour |
| R-3-043 | `GET /statement` contains **money movements only**: an authorization, a release and an expiry are not payments and never appear. A capture appears exactly once, with its links. | s3 §Historical holds | behaviour |
| R-3-044 | **Decision.** An empty window (`from >= to`) is valid, not an error: it returns no entries, `has_more: false`, and `opening_balance == closing_balance` equal to the balance immediately before `from`. | s3 §Statement | behaviour |

## E. The revision model

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-050 | Every payment has a revision history. Revision 1 carries `amount` as originally paid, with `effective_at = recorded_at = created_at` and `reason: ""`. | s3 §Corrections | behaviour |
| R-3-051 | A seeded payment's supplied `created_at` is also its original recorded **and** effective time; omission uses reset time. | s3 §Corrections | behaviour |
| R-3-052 | Each settlement member's original revision uses the settlement's shared `committed_at` as both `effective_at` and `recorded_at`. | s3 §Settlement history | behaviour |
| R-3-053 | Selecting a revision for a view means: take the latest revision **recorded at or before** `known_at`; if none was yet recorded, that payment contributes nothing to the view. | s3 §Corrections | behaviour |
| R-3-054 | Selected revisions are then applied according to their **effective** times, which may precede, equal or follow the payment's `created_at`. | s3 §Corrections | behaviour |
| R-3-055 | **Decision.** The two axes are independent: a correction effective in the past but recorded now is invisible to a `known_at` before its `recorded_at`, and fully visible — at its effective instant — to any `known_at` at or after it. Tests must cover both orderings (effective-before-recorded and effective-equal-to-recorded) rather than assuming they move together. | s3 §Corrections | behaviour |

## F. `POST /payments/{payment_id}/corrections`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-060 | Requires `Idempotency-Key` and the **original sender**; it is the eighth idempotent write path, and all of §7 applies to it. | s3 §Corrections | behaviour |
| R-3-061 | An authenticated non-sender is `403 forbidden` — including the receiver, who may read the history but not correct it. An unknown payment is `404 not_found`. No token is `401 unauthenticated`. | s3 §Corrections | error |
| R-3-062 | All four body fields are required: `expected_revision`, `amount`, `effective_at`, `reason`. A missing one is `422 validation_failed`. | s3 §Corrections | error |
| R-3-063 | `expected_revision` is a positive integer; `amount` is an integer `0..1000000000` (zero reverses the entire payment); `reason` is a string of 1 to 200 characters; `effective_at` is an RFC 3339 instant with an offset **not later than now**. Any violation is `422 validation_failed`. | s3 §Corrections | error |
| R-3-064 | Success is `201` with `{"payment_id", "revision", "amount", "effective_at", "recorded_at", "reason"}`; `recorded_at` is server-assigned. | s3 §Corrections | behaviour |
| R-3-065 | A correction changes neither party and never the visibility. | s3 §Corrections | behaviour |
| R-3-066 | An `expected_revision` that is not the payment's current latest revision is `409 stale_revision` and changes nothing. | s3 §Corrections | error |
| R-3-067 | A successful replay returns **that original revision** with `200`, even after newer revisions exist, and moves no money. A different body with the same key is `409 idempotency_key_reuse`. | s3 §Corrections | behaviour |
| R-3-068 | The difference from the previous selected amount moves between the **same two wallets** in one atomic step: increasing the amount debits the original sender, decreasing it debits the original receiver. | s3 §Corrections | behaviour |
| R-3-069 | A currently unaffordable debit is `409 insufficient_funds`, checked against the debited party's **`available`** (R-2-002, R-2-013). | s3 §Corrections, §Historical holds | error |
| R-3-070 | Otherwise, if any user's `total` **or** `available` would be negative at any past effective/event boundary under the latest known revisions, the correction is `409 historical_overdraft`. | s3 §Corrections, §Historical holds | error |
| R-3-071 | Current unaffordability takes precedence: when a correction is both currently unaffordable and a historical overdraft, the response is `409 insufficient_funds`. | s3 §Historical holds | error |
| R-3-072 | Either failure preserves balances, revision history, statements **and idempotency state** — the key is not claimed (R-1-107), so it stays reusable. | s3 §Corrections | behaviour |
| R-3-073 | **Decision.** Correction precedence, extending R-1-075 and resolving the ladder for this endpoint: `401` → `400 malformed_request` → `400 missing_idempotency_key` → `422` over-long key → idempotency resolution (`200` replay / `409 idempotency_key_reuse`) → `404 not_found` (unknown payment) → `403 forbidden` (not the sender) → `422 validation_failed` (field rules) → `422 linked_payment_immutable` (settlement member or capture) → `409 stale_revision` → `409 insufficient_funds` → `409 historical_overdraft`. Note `404` before `403`: a caller who is not the sender of a payment that does not exist learns only that it does not exist. | §5, s3 §Corrections | error |
| R-3-074 | **Decision.** `effective_at` "not later than now" is evaluated against the server clock at the moment the correction is processed, inclusive: an `effective_at` exactly equal to now is valid. | s3 §Corrections | behaviour |

## G. `GET /payments/{payment_id}/revisions`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-080 | Returns `{"revisions": [...]}` in revision order, **including revision 1** with `reason: ""`. | s3 §Corrections | behaviour |
| R-3-081 | Only the two parties to the payment may read it; a third party gets `404 not_found` **even for a public payment**. No token is `401 unauthenticated`. | s3 §Corrections | error |
| R-3-082 | An unknown payment id is `404 not_found`, indistinguishable from a payment the caller may not read (R-1-078). | s3 §Corrections, §5 | error |
| R-3-083 | **Decision.** Each element carries the same fields as a correction response — `revision`, `amount`, `effective_at`, `recorded_at`, `reason` — so revision 1 and a correction are read the same way. | s3 §Corrections | behaviour |

## H. `known_at` on `GET /me` and `GET /statement`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-090 | Both endpoints accept optional `known_at`, an RFC 3339 instant with an offset; an invalid or empty instant is `422 validation_failed`. | s3 §Corrections | error |
| R-3-091 | Omitting `known_at` means everything known when the read **begins**. | s3 §Corrections | behaviour |
| R-3-092 | `as_of` keeps its inclusive meaning and a statement keeps its half-open window, under any `known_at`. | s3 §Corrections | behaviour |
| R-3-093 | Both query instants may be in the **future**. | s3 §Corrections | behaviour |
| R-3-094 | A supplied `known_at` is echoed back exactly as given. | s3 §Corrections | behaviour |
| R-3-095 | A `known_at` before a payment's revision 1 was recorded makes that payment contribute nothing — not its original amount, and not a zero entry. | s3 §Corrections | behaviour |

## I. Snapshot tokens

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-100 | Every **first** `GET /statement` response — one made without `snapshot` — additionally returns an opaque `snapshot` token. | s3 §Stable pagination | behaviour |
| R-3-101 | The token freezes the caller's selected revisions, window, balances, entries and **default `to`** at that read. | s3 §Stable pagination | behaviour |
| R-3-102 | `GET /statement?snapshot=<token>&limit=…&offset=…` pages that exact result, even after later payments or corrections. | s3 §Stable pagination | behaviour |
| R-3-103 | Only `limit` and `offset` may accompany a snapshot; supplying `from`, `to` or `known_at` with it is `422 validation_failed`. | s3 §Stable pagination | error |
| R-3-104 | An unknown token, **another user's** token, or a token issued before the last reset is `404 not_found`. | s3 §Stable pagination | error |
| R-3-105 | Tokens last until reset; no survival across a container restart is required. | s3 §Stable pagination | behaviour |
| R-3-106 | Paging a snapshot changes neither balances nor entries, and `has_more` is correct on the final partial page and for offsets beyond the end. | s3 §Stable pagination | behaviour |
| R-3-107 | Unrecognized query parameters remain ignored (R-1-023), including alongside a snapshot. | s3 §Stable pagination | behaviour |
| R-3-108 | A correction may move a payment **into or out of** a statement window; existing snapshots remain unchanged through concurrent payments and corrections. | s3 §Stable pagination | invariant |
| R-3-109 | Old snapshots remain unchanged after any authorization lifecycle action — capture, void or expiry — as well as after any correction. | s3 §Historical holds | invariant |
| R-3-110 | **Decision.** A snapshot token is an opaque string of at most 64 characters (R-1-024) and must not be a forgeable encoding of its own contents: a token the service did not issue is `404`, so tests may assert that a mutated or self-constructed token is rejected. | §3.4, s3 §Stable pagination | behaviour |
| R-3-111 | **Decision.** A response to a snapshot-paged read also carries the `snapshot` field, set to that same token, so a caller paging a snapshot need not retain the token separately. | s3 §Stable pagination | behaviour |

## J. Settlement history and linked payments

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-120 | Stage-1 settlements retain their original receipts and privacy rules unchanged. | s3 §Settlement history | behaviour |
| R-3-121 | A single-payment correction of a **settlement member** is `422 linked_payment_immutable`. | s3 §Settlement history | error |
| R-3-122 | A correction of a **capture** is `422 linked_payment_immutable`. | s3 §Settlement history | error |
| R-3-123 | Ordinary direct payments and request payments remain correctable. | s3 §Settlement history, s4 | behaviour |

## K. Upgrade from stages 1 and 2

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-130 | A stage-3 service accepts, unchanged, an export produced by the team's **stage-1 or stage-2** service, returning `204`, and everything R-1-205/R-1-206/R-2-175 require survives. | s3 §Settlement history | behaviour |
| R-3-131 | The ledger imports and accounts for authorizations and captures: imported holds affect `held` and `available`, and imported captures appear in statements exactly once with their links. | s3 §Settlement history, §Historical holds | behaviour |
| R-3-132 | An imported payment with no revision history gains revision 1 derived per R-3-050/R-3-051, with no money moving and no balance changing. | s3 §Corrections | behaviour |
| R-3-133 | A stage-3 export round-trips revisions, snapshots' validity domain (tokens need not survive an import), `closed_at` and everything stages 1 and 2 require. | s3, §10 | behaviour |

## L. Historical holds

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-140 | For `GET /me?as_of=T&known_at=K`, all four money fields describe that same view: `balance = total` and `available = total − held`. | s3 §Historical holds | behaviour |
| R-3-141 | A hold starts at authorization **creation**; a nonfinal capture reduces it at capture time; a final capture, a void or an expiry releases the remainder at that event's time. | s3 §Historical holds | behaviour |
| R-3-142 | Expiry takes effect at `expires_at`. Events other than clock expiry are known at their server-assigned event time. | s3 §Historical holds | behaviour |
| R-3-143 | Once an authorization's creation is known, its expiry **deadline** is known too — so a `known_at` that sees the creation also sees the expiry that follows from it. | s3 §Historical holds | behaviour |
| R-3-144 | For a query beyond now, an open hold expires at its deadline. | s3 §Historical holds | behaviour |
| R-3-145 | Without `as_of`, the view instant is the instant the request began. | s3 §Historical holds | behaviour |
| R-3-146 | Authorizations expose `closed_at`: `null` while open, the event time when closed. | s3 §Historical holds | behaviour |
| R-3-147 | Historical `total` follows the stage-3 effective/recorded-time rules (R-3-053, R-3-054). | s3 §Historical holds | behaviour |
| R-3-148 | Seeded **open** holds are assumed created at reset unless `created_at` is supplied; seeded **closed** holds need not reconstruct a prior lifecycle. | s3 §Historical holds | behaviour |
| R-3-149 | **Decision.** A seeded closed hold contributes no hold at any historical instant, since its lifecycle is not reconstructed; it is therefore never counted in `held` for any `as_of`. | s3 §Historical holds | behaviour |

## M. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-160 | Two concurrent corrections using the **same** `expected_revision` cannot both succeed: exactly one returns `201` and the other `409 stale_revision`. Money moves once. | s3 §Stable pagination | invariant |
| R-3-161 | A correction concurrent with a payment between the same two wallets remains serializable, and the conservation and nonnegativity invariants hold at every read. | s3 §Corrections | invariant |
| R-3-162 | A statement read concurrent with a correction returns a self-consistent view: `opening_balance` plus its deltas equals `closing_balance` (R-3-034) even if a correction commits mid-read. | s3 §Statement | invariant |
| R-3-163 | Under a storm of mixed payments, request payments, splits, settlements, authorizations, captures, voids and corrections with ~30% replays, every invariant in section A and in stages 1 and 2 holds. | s3, §1 | invariant |
| R-3-164 | Historical reads are stable under load: the same `as_of`/`known_at` pair, queried twice with writes in between, returns the same balance for instants at or before the first read's start. | s3 §Corrections | invariant |
