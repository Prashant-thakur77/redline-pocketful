# Stage 3 status

Folder `stage-3/` is the copy-forward of stage 2 at `bc6a8cc` (commit `8dfcc60`).
Stage 3 opens with its own fresh budget: 480 minutes, $120 (`factory/budget.yaml`).

| id | state | commit | evidence |
|---|---|---|---|
| N3-T | dispatched | — | — |
| N3-1 | planned | — | — |
| N3-2 | planned | — | — |
| N3-3 | planned | — | — |
| N3-4 | planned | — | — |
| N3-5 | planned | — | — |
| N3-6 | planned | — | — |
| N3-7 | planned | — | — |
| N3-8 | planned | — | — |
| N3-9 | planned | — | — |
| N3-10 | planned | — | — |
| N3-11 | planned | — | — |

States: planned → dispatched → built → attacked → GO | NEEDS_WORK | blocked.

Stage: open.

## Carried into this stage from stage 2's partial close

Three gate-6 survivors at stage 2's close are genuine test gaps, not code defects, and
they carry into N3-T as work rather than as a reason to stop:

1. `routes/authorizations.py:32` — single-field-missing on `POST /authorizations` is never
   fed, so an `or`/`and` flip in the required-field check survives.
2. `snapshot.py:62` — `_require_int`'s bool-vs-int check; the mutant makes the check unable
   to reject anything, so a non-integer `seq`/`next_seq` would import uncaught.
3. `fixtures.py:36` — an id at exactly `MAX_ID_LEN` is never exercised (boundary gap).

@redline must cover all three in N3-T; they are the cheapest route back over the 80% bar.

## Housekeeping found in the copy-forward

`stage-3/_restart_server.py`, `stage-3/_server.log` and `stage-3/tests/_manual_check_n24b.py`
are stage-2 working scratch that the copy carried forward. They go out at N3-1 (builder) and
N3-T (the tests one, redline) — a stray `_server.log` in the image is also a gate-1 risk.
