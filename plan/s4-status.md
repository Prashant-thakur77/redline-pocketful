# Stage 4 status

Opened 2026-10-05T12:30Z, when stage 3's 480-minute clock ran out (495.5 min) and stage 3 was
recorded **partial**. Fresh caps: 480 minutes, $120.

**This file is the authoritative record for stage 4.** If a room message and this file disagree,
this file wins; check `git log -1 -- plan/s4-status.md` for freshness. The last `TICK` at the end
is the live block.

Requirements: `plan/s4-requirements.md` (R-4-001 … R-4-083, plus every carried R-1-*/R-2-*/R-3-*).
Plan: `plan/s4-dag.md` (N4-T … N4-8).

## Stage 4 inherits unfinished stage-3 work, and that is deliberate

Stage 4 carries every stage-1/2/3 requirement, so the six stage-3 items that were never dispatched
are still binding here and are **re-homed as stage-4 items**, keeping their original requirement
ids so nothing is renumbered:

| re-homed from | content | requirements | new id |
|---|---|---|---|
| N3-6 | historical overdraft at every effective/event boundary, `insufficient_funds` first | R-3-002, R-3-059, R-3-060, R-3-118, R-3-133 | N4-C1 |
| N3-8 | historical holds: hold timeline, `closed_at`, expiry at deadline, four-field historical view | R-3-110…120 | N4-C2 |
| N3-9 | import of stage-1 and stage-2 exports, revision 1 synthesis | R-3-100, R-3-102 | N4-C3 |
| N3-7 | snapshot token scope-to-user and clear-on-reset (the freeze itself landed as R-3-092) | R-3-005, R-3-081…091 | N4-C4 |
| N3-10 | statement and correction UI, carried stage-2 screens intact | R-2-090…160 carried, s3 UI | N4-C5 |
| N3-11 | correction storm, snapshot-under-correction races, concurrent same-revision corrections | R-3-001, R-3-067, R-3-130…133 | N4-C6 |

Dispatch priority, highest first: **N4-T** (tests) → **N4-C1, N4-C2** (money-conservation gaps in
the closed stage-3 content — these protect the dispatch's own invariants) → **N4-1, N4-2**
(refunds) → **N4-3 … N4-5** (correction batches) → **N4-C3, N4-C4** → **N4-6** → **N4-C5, N4-C6,
N4-7, N4-8** as the clock allows. The money invariants outrank new surface area: if the clock runs
out, stage 4 is recorded partial with refunds and the historical-overdraft repairs in, rather than
with every endpoint half-built.

## Items

| id | state | commit | evidence |
|---|---|---|---|
| N4-copy | dispatched to @builder — `stage_copy stage-3 stage-4` after @redline's N3-T.4 sha lands | — | — |
| N4-T | queued for @redline, after N4-copy | — | — |
| N4-C1 … N4-C6 | planned (re-homed stage-3 items) | — | — |
| N4-1 … N4-8 | planned | — | — |

States: planned → queued → dispatched → built → attacked → GO | NEEDS_WORK | blocked.

## TICK 2026-10-05T12:30Z — stage 4 opened

Nothing built yet. Three seats have an action, all dispatched in one round:

1. @redline — commit the N3-T.4 test repairs into `stage-3/tests/` immediately (they are
   uncommitted and would be lost by the copy-forward), tell @builder the sha, then stand by for
   N4-T once `stage-4/` exists.
2. @builder — commit N3-5 (`known_at`) immediately, then on @redline's sha run
   `python -m factory.stage_copy stage-3 stage-4`, commit `stage-4/`, and name that sha as the
   final stage-3 content sha.
3. @verifier — one measurement run of stage 3 at that sha, `--gates all`, for the partial record.
   It holds the only gate run; no other seat runs container gates until it reports.

Stage 3's partial is already in the ledger, so this measurement refines the record and cannot
reopen an item.
