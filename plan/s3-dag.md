# Stage 3 work plan — `stage-3/`

`stage-3/` starts as a copy-forward of the closed `stage-2/`
(`python -m factory.stage_copy stage-2 stage-3`), so every R-1-* and R-2-*
requirement is satisfied on arrival and must stay satisfied (gate 5).

Stage 3 is where the checks go mostly hidden, so the test effort weights here and
at stage 4. Two structural warnings carried forward:

- **Gate 7 must be proven non-vacuous**, per `plan/s2-dag.md` G7-1 … G7-4. A gate that
  records nothing is indistinguishable from one that passed. Stage 3 adds no required
  route, but the stage-2 routes must still be visited and the `g7` ledger event must exist.
- **Gate 2's ratchet floor** is whatever the highest recorded count is when stage 3 opens.
  Dispatch gate runs with `--commit <sha>` so recorded counts describe committed state
  (`plan/lessons.md`, `ee723d1`).

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| N3-T | Tests and gate hook for bitemporal reads, corrections, snapshots | all R-3-* | — | redline |
| N3-1 | Payment `created_at` as an effective instant: seeded `created_at`, future-dated rejection, opening-balance derivation | R-3-010 … R-3-016, R-3-020 … R-3-023 | N3-T | builder |
| N3-2 | Revision history: revision 1 for every payment incl. seeded and settlement members, immutable append, strictly increasing `recorded_at` | R-3-040 … R-3-048 | N3-1 | builder |
| N3-3 | `GET /me?as_of=` — balance as of an instant, inclusive boundary, echo, 422 on a non-instant | R-3-030 … R-3-036 | N3-1 | builder |
| N3-4 | `GET /statement` — half-open window, oldest-first, `balance_after`, opening/closing, pagination invariance | R-3-050 … R-3-062 | N3-3 | builder |
| N3-5 | `POST /payments/{id}/corrections` — validation, precedence, `stale_revision`, the two-wallet delta, `insufficient_funds` before `historical_overdraft` | R-3-070 … R-3-085 | N3-2, N3-4 | builder |
| N3-6 | `known_at` recorded-time selection on `/me` and `/statement`, and statement ordering by selected `effective_at` | R-3-090 … R-3-099 | N3-5 | builder |
| N3-7 | `GET /payments/{id}/revisions` — revision order, party-only visibility, 404 for third parties even when public | R-3-100 … R-3-104 | N3-2 | builder |
| N3-8 | `snapshot` tokens — freeze selected revisions/window/balances, limit+offset only, 404 rules, lifetime to reset | R-3-110 … R-3-122 | N3-6 | builder |
| N3-9 | Linked-payment immutability and historical holds: `linked_payment_immutable` for settlement members and captures, hold lifecycle in historical views, `closed_at` | R-3-130 … R-3-136, R-3-140 … R-3-150 | N3-5 | builder |
| N3-10 | Export/import accepting stage-1 and stage-2 exports, carrying revisions, snapshots and hold lifecycle | R-3-160 … R-3-166 | N3-8, N3-9 | builder |
| N3-11 | UI for corrected history and statements; gate 7 non-vacuous | R-3-170 … R-3-176 | N3-6 | builder |
| N3-12 | Hardening: concurrent corrections on one expected revision, snapshot stability under concurrent writes, conservation in every historical view | R-3-001 … R-3-006, R-3-180 … R-3-186 | N3-10, N3-11 | builder |

Dispatch order: N3-T → N3-1 → (N3-2, N3-3) → N3-4 → N3-5 → (N3-6, N3-7) → N3-8 → N3-9 → N3-10 → N3-11 → N3-12.

Gates per item: `--gates 1,2,4,8 --commit <sha>`; N3-11 adds gate 7.

## The three traps this stage, flagged in advance

1. **Bitemporality is two independent axes.** `as_of` selects by *effective* time and is
   inclusive; `known_at` selects by *recorded* time, also at-or-before; a statement window
   stays half-open. Every combination must work, including both instants in the future.
   The likeliest defect is one axis silently applied to the other.
2. **Error precedence inside corrections is ordered and testable:** item validation →
   `linked_payment_immutable` → current `insufficient_funds` → `historical_overdraft` at
   every effective/event boundary. A correction that is affordable now but overdraws a past
   boundary must give `historical_overdraft`, not succeed.
3. **Snapshots must be genuinely frozen.** A snapshot taken before a correction must page
   identically after it. The cheap wrong implementation re-derives from live state and passes
   every single-read test.
