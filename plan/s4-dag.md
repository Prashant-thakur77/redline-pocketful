# Stage 4 work plan — `stage-4/`

`stage-4/` starts as a copy-forward of the closed `stage-3/`
(`python -m factory.stage_copy stage-3 stage-4`), so every R-1-*, R-2-* and R-3-*
requirement arrives satisfied and must stay satisfied — gate 5's job.

Stage 4's checks are mostly hidden, like stage 3's. The surface is small but it sits on
top of the bitemporal machinery, so almost every requirement here is an interaction with
something already built rather than a new subsystem.

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| N4-T | Tests and gate hook for refunds, batch corrections and their interactions with corrections, holds, settlements and snapshots | all R-4-*, carried R-1-*/R-2-*/R-3-* | — | redline |
| N4-1 | `POST /payments/{id}/refunds`: target kinds, permission, cumulative ceiling, available-funds debit, `refund_of` on every payment | R-4-001, R-4-010…024 | N4-T | builder |
| N4-2 | Refund/correction interactions: refunds immutable, correction floor at the refunded amount, correction debits against `available` | R-4-002, R-4-030…034 | N4-1 | builder |
| N4-3 | `POST /correction-batches`: operator permission, shape and item validation, settlement completeness, identical effective instants | R-4-040…048, R-4-060, R-4-061 | N4-2 | builder |
| N4-4 | Batch commit semantics: shared `recorded_at`, `correction_batch_id` on revisions, input-order response, all-or-nothing, replay | R-4-003, R-4-004, R-4-052…058 | N4-3 | builder |
| N4-5 | Batch error precedence and combined affordability, current then historical | R-4-049, R-4-050, R-4-051 | N4-4 | builder |
| N4-6 | Import of stage-1/2/3 exports, retaining settlement membership, corrections and snapshots | R-4-070, R-4-072 | N4-1 | builder |
| N4-7 | ~~UI for refunds and batch corrections~~ **CANCELLED 2026-10-06T01:50Z — not a requirement.** `stage-4.md` and `stage-3.md` contain **zero** occurrences of `data-testid`, `browser`, `screen` or `route`; every UI requirement in the track comes from `stage-2.md` (7 `data-testid` mentions) and is carried forward intact, which gate 7 verifies and which is already PASS. Building refund or statement screens would be inventing surface the specification does not ask for. Only the carried R-2-090…188 apply. | carried R-2-090…188 (satisfied, g7 PASS) | — | none |
| N4-8 | Hardening: concurrent refunds, refund-vs-correction races, concurrent batches sharing a payment | R-4-059, R-4-080…083 | N4-5, N4-6 | builder |

Dispatch order: N4-T → N4-1 → N4-2 → N4-3 → N4-4 → N4-5 → (N4-6, N4-7) → N4-8.

## Amendments made when stage 4 actually opened (2026-10-05T17:10Z)

- **`N4-T` is dispatched as `N4-T.2`**, and the copy-forward as `N4-copy.2`. The original ids were
  dispatched at 12:30 and withdrawn when stage 3 reopened; their ledger events survive, so the
  governor still counts their clock from 12:30 and gate 8 fails them on arrival. See
  `plan/s4-status.md`.
- **The two re-homed stage-3 items fold into existing rows rather than adding new ones:**
  N4-C5 (stage 3's never-dispatched statement and correction UI) widens **N4-7**; N4-C6 (stage 3's
  never-dispatched correction-storm item) widens **N4-8**. The other four items re-homed at 12:30
  (N4-C1…C4) all landed inside stage 3 and arrive with the copy.
- **N4-7 is last by priority, not by dependency.** Gate 7 is already green on the carried stage-2
  screens, so the UI is the only item whose absence costs nothing a gate measures, while every item
  above it is a hidden check. If the clock runs out, stage 4 is partial with refunds and batch
  corrections in and the statement/refund screens absent — never the reverse.

## The four traps I expect to cost the most

1. **The refund ceiling is the *current corrected* amount, not the original** (R-4-015), and the
   correction floor is the *already-refunded* amount (R-4-033). They are two directions of one
   constraint, and a service that stores only the original amount gets both wrong.
2. **Batch `recorded_at` is shared and must be strictly later than every member's previous
   `recorded_at`** (R-4-053). With one shared timestamp across up to 32 payments, a naive `now()`
   can tie with a correction recorded in the same tick and silently break R-3-004.
3. **Settlement completeness is over the union of settlements the batch touches** (R-4-045,
   R-4-060), and it is checked *after* per-item errors in input order. Both halves are easy to
   get backwards.
4. **Earlier snapshot tokens must keep paging frozen entries after a batch** (R-4-057). A batch is
   the largest single mutation in the product, so it is the most likely thing to leak into a token
   that R-3-005 froze.
