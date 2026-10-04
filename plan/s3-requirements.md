# Stage 3 requirements — pocketful: statements and payment corrections

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-3.md`.
`§` references are to `stage-1.md` unless prefixed `s2`/`s3`.

**Every requirement in `plan/s1-requirements.md` and `plan/s2-requirements.md` continues
to apply in `stage-3/`**, except where a row below amends one. Stage 3's checks are
mostly hidden, so the rows marked **[derived]** are requirements no example in the spec
shows; they carry the same weight as the rest.

Kinds: **invariant**, **behaviour**, **error**, **limit**, **UI**.

## A. Invariants

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-001 | The sum of all balances equals the seeded total **in every historical view**: for any `as_of`/`known_at` pair, summing every user's `balance` at that view equals the total seeded by the last reset. | s3 §corrections | invariant |
| R-3-002 | A correction appends an **immutable** revision; it never mutates revision 1 or any earlier revision, never changes the parties, and never changes `visibility`. | s3 §corrections | invariant |
| R-3-003 | `recorded_at` values for one payment strictly increase with revision number; no two revisions of one payment share a `recorded_at`. | s3 §corrections | invariant |
| R-3-004 | The original payment, `GET /activity`'s view of it, and every original idempotent response remain unchanged by any correction, forever. | s3 §corrections | invariant |
| R-3-005 | A correction's difference moves between the **same two wallets** in the same atomic step as the revision is appended; either both happen or neither does. | s3 §corrections | invariant |
| R-3-006 | A rejected correction preserves balances, revision history, statements, snapshots and idempotency state exactly. | s3 §corrections | invariant |
| R-3-007 | No balance — total or available — is negative at any effective/event boundary in any historical view, under the latest known revisions. | s3 §corrections, §Historical holds | invariant |
| R-3-008 | Concurrent corrections using the same `expected_revision` on one payment cannot both succeed. | s3 §Stable pagination | invariant |
| R-3-009 | An existing `snapshot` token's entries, balances, selected revisions, window and default `to` never change, for any later payment, correction, capture, void or expiry. | s3 §Stable pagination, §Historical holds | invariant |
| R-3-010 | **[derived]** `opening_balance + Σ delta == closing_balance` holds for the full window of every statement, in every `known_at` view, including when corrections moved payments into or out of the window. | s3 §statement 3 | invariant |

## B. Payment timestamps

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-020 | Every payment's `created_at` is an RFC 3339 instant with an offset identifying when it moved money, and every endpoint that returns a payment includes it. | s3 §timestamps | behaviour |
| R-3-021 | `GET /activity` retains its existing ordering by `created_at`, newest first (R-1-190), unchanged by corrections. | s3 §timestamps | behaviour |
| R-3-022 | A seeded payment may supply `created_at`; omission uses reset time, ordered before every subsequent API-created payment. | s3 §timestamps | behaviour |
| R-3-023 | A seeded payment whose `created_at` is in the future is `422 validation_failed` from `POST /_test/reset`, with no state change. | s3 §timestamps | error |
| R-3-024 | A fixture's `balance` remains the balance after all seeded payments; loading seeded payments must not change it (R-1-043 unchanged). | s3 §timestamps | behaviour |
| R-3-025 | **[derived]** A seeded `created_at` that is not an RFC 3339 instant with an explicit offset is `422 validation_failed` from reset, with no state change. | s3 §timestamps, §5 | error |
| R-3-026 | **[derived]** Two seeded payments may share a `created_at`; ties break by payment id ascending wherever ordering is specified (R-3-040). | s3 §statement 1 | behaviour |

## C. `GET /me?as_of=`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-030 | `as_of` is optional and must be an RFC 3339 instant **with an offset**; a naive local time, a bare date, an empty value or any other form is `422 validation_failed`. | s3 §me | error |
| R-3-031 | Without any temporal query parameter, `GET /me` keeps its existing money fields and reports **current corrected** values. | s3 §me | behaviour |
| R-3-032 | With `as_of`, `balance` is the caller's balance as it stood at that instant: after every payment of theirs with `created_at` **at or before** `as_of`, and before every payment after it. A payment at exactly `as_of` counts as having happened. | s3 §me | behaviour |
| R-3-033 | An `as_of` at or after the latest payment returns the current balance. | s3 §me | behaviour |
| R-3-034 | An `as_of` before the earliest payment returns the **opening balance** — what the wallet held before anything moved. | s3 §me | behaviour |
| R-3-035 | The response carries `as_of` back **exactly as given**, byte for byte, including the offset spelling. | s3 §me | behaviour |
| R-3-036 | Opening balances equal seeded ending balances minus the net effect of the **original** seeded payments; corrections must never change an opening balance. New accounts open at zero. | s3 §corrections | behaviour |
| R-3-037 | `as_of` may be in the future; the result equals the current view. | s3 §known_at | behaviour |
| R-3-038 | **[derived]** With `as_of`, all four money fields describe that same view: `balance == total`, `available == total - held`, `held` the holds open at that instant. | s3 §Historical holds | behaviour |

## D. `GET /statement`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-040 | `GET /statement` returns the payments the caller sent or received in the half-open window `[from, to)`, **oldest first**, ordered by selected `effective_at` ascending then payment id ascending for ties. | s3 §statement, §corrections | behaviour |
| R-3-041 | `from` and `to` are optional: `from` defaults to the opening of the wallet, `to` to now. Both must be RFC 3339 instants with an offset; anything else is `422 validation_failed`. | s3 §statement | error |
| R-3-042 | `limit` and `offset` behave exactly as on `GET /requests` (R-1-073, R-1-074, R-1-166, R-1-167). | s3 §statement | behaviour |
| R-3-043 | The response is `{"opening_balance", "entries":[{"payment","delta","balance_after","revision","effective_at","recorded_at"}…], "closing_balance", "has_more", "snapshot"}`. | s3 §statement | behaviour |
| R-3-044 | `opening_balance` is the caller's balance immediately **before** `from`; `closing_balance` is the balance immediately **before** `to`. | s3 §statement 2 | behaviour |
| R-3-045 | A sent payment has a negative `delta`; a received payment has a positive `delta`. | s3 §statement 3 | behaviour |
| R-3-046 | Pagination never changes an entry's `balance_after`, nor the window's `opening_balance` or `closing_balance`: those describe the **full** window regardless of `limit` and `offset`. | s3 §statement 4 | behaviour |
| R-3-047 | Only payments the caller sent or received appear in their statement, including when other payments are `public`; the activity-feed visibility rules do **not** apply to statements. | s3 §statement | behaviour |
| R-3-048 | `payment.amount` in an entry is the **selected** revision's amount for this statement, not necessarily the original. | s3 §known_at | behaviour |
| R-3-049 | A zero-amount revision still appears as an entry, with `delta` zero. | s3 §known_at | behaviour |
| R-3-050 | A correction is never counted alongside the revision it replaces: exactly one revision per payment contributes to a statement. | s3 §known_at | behaviour |
| R-3-051 | With no corrections and no `known_at`, statement behaviour is identical to a stage-2 service's. | s3 §known_at | behaviour |
| R-3-052 | `GET /statement` contains money movements only: authorization, release and expiry are not payments and never appear. Captures appear exactly once, with their links. | s3 §Historical holds | behaviour |
| R-3-053 | **[derived]** An empty window returns `entries: []`, `has_more: false`, and `opening_balance == closing_balance`. | s3 §statement | behaviour |
| R-3-054 | **[derived]** A `from` later than `to` yields an empty window (not an error), with `opening_balance` and `closing_balance` each computed at their own instant. | s3 §statement | behaviour |

## E. Corrections

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-060 | Every payment has a revision history. Revision 1 has `amount` as originally paid and `effective_at == recorded_at == created_at`. A seeded payment's supplied `created_at` is also its original recorded and effective time; omission uses reset time. | s3 §corrections | behaviour |
| R-3-061 | `POST /payments/{payment_id}/corrections` requires an idempotency key and the **original sender**. | s3 §corrections | behaviour |
| R-3-062 | An authenticated non-sender gets `403 forbidden`; an unknown payment gets `404 not_found`; no token is `401 unauthenticated`. | s3 §corrections | error |
| R-3-063 | Body is `{"expected_revision","amount","effective_at","reason"}` and **all four fields are required**; a missing one is `422 validation_failed`. | s3 §corrections | error |
| R-3-064 | `expected_revision` is a positive integer; `amount` is an integer `0..1000000000` (zero reverses the entire payment); `reason` is a string of 1..200 characters; `effective_at` is an RFC 3339 instant **not later than now**. Any violation is `422 validation_failed`. | s3 §corrections | error |
| R-3-065 | Success is `201` with `{"payment_id","revision","amount","effective_at","recorded_at","reason"}`, `recorded_at` server-assigned. | s3 §corrections | behaviour |
| R-3-066 | A stale `expected_revision` (not the payment's current latest) is `409 stale_revision`. | s3 §corrections | error |
| R-3-067 | A successful replay returns that original revision with `200`, even after newer revisions exist; a different body with the same key is `409 idempotency_key_reuse`. | s3 §corrections | behaviour |
| R-3-068 | The difference from the previous amount moves between the same two wallets atomically: **increasing** the amount debits the original sender, **decreasing** it debits the original receiver. | s3 §corrections | behaviour |
| R-3-069 | A currently unaffordable debit is `409 insufficient_funds`, checked against **available** funds (stage 2's R-2-013, and stage 4 restates it). | s3 §corrections, s4 | error |
| R-3-070 | Otherwise, if any user's corrected balance is negative at **any** effective-time boundary, the correction is `409 historical_overdraft`. Balances at a boundary include the combined effect of all movements at that instant. | s3 §corrections | error |
| R-3-071 | Current unaffordable debits take precedence over historical ones: `insufficient_funds` is evaluated before `historical_overdraft`. | s3 §Historical holds | error |
| R-3-072 | `GET /payments/{payment_id}/revisions` returns `{"revisions":[…]}` in revision order, **including revision 1** with `reason: ""`. | s3 §corrections | behaviour |
| R-3-073 | Only the two parties may read a payment's revisions; a third party gets `404 not_found` **even for a public payment**; no token is `401 unauthenticated`. | s3 §corrections | error |
| R-3-074 | Correction records are not new feed payments: `GET /activity` continues to display the original payment, unchanged. | s3 §corrections | behaviour |
| R-3-075 | A single-payment correction of a **settlement member** is `422 linked_payment_immutable`. | s3 §Settlement history | error |
| R-3-076 | A correction of a **capture** is `422 linked_payment_immutable`; captures are immutable linked payments. | s3 §Settlement history | error |
| R-3-077 | **[derived]** Correction error precedence, in order: `401` → body parse `400` → `400 missing_idempotency_key` → key length `422` → idempotency resolution (`200`/`409 idempotency_key_reuse`) → field validation `422` → `404 not_found` → `403 forbidden` (non-sender) → `422 linked_payment_immutable` → `409 stale_revision` → `409 insufficient_funds` → `409 historical_overdraft`. | s3 §corrections, R-1-075 | error |
| R-3-078 | **[derived]** A correction whose `amount` equals the current amount is valid and appends a revision that moves zero money. | s3 §corrections | behaviour |
| R-3-079 | **[derived]** `effective_at` may be earlier than the payment's `created_at`; the revision then takes effect at that earlier instant and historical views reflect it, subject to R-3-070. | s3 §corrections | behaviour |

## F. `known_at` — recorded-time views

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-090 | `GET /me` and `GET /statement` accept optional `known_at`, an RFC 3339 instant with an offset; an invalid or empty value is `422 validation_failed`. | s3 §known_at | error |
| R-3-091 | For each payment, select its **latest revision recorded at or before `known_at`**; if none was yet recorded, that payment contributes nothing at all. | s3 §known_at | behaviour |
| R-3-092 | Omitting `known_at` means everything known when the read begins. | s3 §known_at | behaviour |
| R-3-093 | Selected revisions are then applied according to their **effective** times; `as_of` keeps its inclusive meaning and a statement keeps its half-open window. | s3 §known_at | behaviour |
| R-3-094 | Both query instants may be in the future. | s3 §known_at | behaviour |
| R-3-095 | A supplied `known_at` is echoed back **exactly** as given. | s3 §known_at | behaviour |
| R-3-096 | **[derived]** `as_of` and `known_at` compose: `GET /me?as_of=T&known_at=K` selects revisions by `K` and then evaluates balance at effective instant `T`. | s3 §Historical holds | behaviour |
| R-3-097 | **[derived]** A `known_at` earlier than the first payment's `recorded_at` yields the opening balance and an empty statement. | s3 §known_at | behaviour |

## G. Stable statement pagination — `snapshot`

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-100 | Every **first** `GET /statement` response additionally returns an opaque `snapshot` token. | s3 §Stable pagination | behaviour |
| R-3-101 | The token freezes the caller's selected revisions, window, balances, entries **and default `to`** at that read. | s3 §Stable pagination | behaviour |
| R-3-102 | `GET /statement?snapshot=<token>&limit=…&offset=…` pages that exact result, even after later payments or corrections. | s3 §Stable pagination | behaviour |
| R-3-103 | Only `limit` and `offset` may accompany a snapshot; supplying `from`, `to` or `known_at` with it is `422 validation_failed`. | s3 §Stable pagination | error |
| R-3-104 | An unknown token, another user's token, or a token issued before the last reset is `404 not_found`. | s3 §Stable pagination | error |
| R-3-105 | Tokens last until reset; no survival across a container restart is required. | s3 §Stable pagination | behaviour |
| R-3-106 | Paging a snapshot changes neither balances nor entries; the final partial page and offsets beyond the end report `has_more` correctly. | s3 §Stable pagination | behaviour |
| R-3-107 | Unrecognized query parameters remain ignored under R-1-023. | s3 §Stable pagination | behaviour |
| R-3-108 | A correction may move a payment into or out of a statement window; existing snapshots remain unchanged during concurrent payments or corrections. | s3 §Stable pagination | behaviour |
| R-3-109 | **[derived]** A paged snapshot response echoes the same `snapshot` token, and `opening_balance`/`closing_balance` are the frozen values on every page. | s3 §Stable pagination | behaviour |
| R-3-110 | **[derived]** A snapshot token is opaque: at most 64 characters (R-1-024) and not required to encode anything the caller can read. | §3.4 | behaviour |

## H. Settlement and capture history

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-120 | Stage-1 settlements retain their original receipts and privacy rules. | s3 §Settlement history | behaviour |
| R-3-121 | Each settlement member's original revision uses its shared `committed_at` as **both** `effective_at` and `recorded_at`. | s3 §Settlement history | behaviour |
| R-3-122 | A stage-3 service accepts, unchanged, exports produced by the team's stage-1 **or** stage-2 service. | s3 §Settlement history | behaviour |
| R-3-123 | The ledger imports and accounts for authorizations and captures from a stage-2 export. | s3 §Settlement history | behaviour |
| R-3-124 | **[derived]** A stage-3 export round-trips every revision, every `snapshot` token still valid, and all correction idempotency records, in addition to R-1-205/206 and R-2-175. | s3, §10 | behaviour |

## I. Historical holds

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-130 | For `GET /me?as_of=T&known_at=K`, all four money fields describe that same view: `balance == total`, `available == total - held`. | s3 §Historical holds | behaviour |
| R-3-131 | A hold starts at authorization creation; a nonfinal capture reduces it at capture time; a final capture, a void or an expiry releases the remainder at that event's time. Expiry takes effect at `expires_at`. | s3 §Historical holds | behaviour |
| R-3-132 | Events other than clock expiry are known at their server-assigned event time; once a creation is known, its expiry deadline is known too. | s3 §Historical holds | behaviour |
| R-3-133 | For queries beyond now, an open hold expires at its deadline. | s3 §Historical holds | behaviour |
| R-3-134 | Without `as_of`, the view instant is the instant the request began. | s3 §Historical holds | behaviour |
| R-3-135 | Authorizations expose `closed_at`: `null` while open, the event time when closed. | s3 §Historical holds | behaviour |
| R-3-136 | Historical `total` follows stage-3 effective/recorded-time rules. | s3 §Historical holds | behaviour |
| R-3-137 | A correction is `409 historical_overdraft` if it makes **either** `total` or `available` negative at any past effective/event boundary, under the latest known revisions. | s3 §Historical holds | error |
| R-3-138 | Seeded **open** holds are assumed created at reset unless `created_at` is supplied; seeded **closed** holds need not reconstruct a prior lifecycle. | s3 §Historical holds | behaviour |
| R-3-139 | Old snapshots remain unchanged after any authorization lifecycle action or any correction. | s3 §Historical holds | invariant |
| R-3-140 | **[derived]** A seeded authorization may supply `created_at`; if supplied it must be an RFC 3339 instant with an offset, not later than reset time, else `422 validation_failed`. | s3 §Historical holds, §5 | error |

## J. UI

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-150 | Every stage-2 UI requirement (R-2-090 … R-2-160) continues to hold unchanged: the same routes, `data-testid` contract, formatting, responsive and accessibility rules. | s2 §UI | UI |
| R-3-151 | **[derived]** Nothing in stage 3 requires a new screen; corrections, statements and temporal queries are API-only. The existing screens must not regress, and a corrected payment continues to display its **original** amount in the activity feed (R-3-004, R-3-074). | s3 §corrections | UI |

## K. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-3-160 | Two concurrent corrections of one payment with the same `expected_revision` produce exactly one `201`; the other is `409 stale_revision`. | s3 §Stable pagination | invariant |
| R-3-161 | A correction concurrent with a statement read never produces a torn statement: the read reflects either the pre- or post-correction state in full. | s3 §Stable pagination | invariant |
| R-3-162 | Under a storm of payments, request payments, splits, settlements, authorizations, captures, voids and corrections with ~30% replays, R-3-001 … R-3-010 and all stage-1/2 invariants hold. | s3, s2 §Concurrent | invariant |
