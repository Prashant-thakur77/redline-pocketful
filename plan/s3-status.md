# Stage 3 status

Folder `stage-3/` is the copy-forward of stage 2 at `bc6a8cc` (commit `8dfcc60`).
Stage 3 opens with its own fresh budget: 480 minutes, $120 (`factory/budget.yaml`).

| id | state | commit | evidence |
|---|---|---|---|
| N3-T | accepted (one residual fix N3-T.1) | `846862a` | 573 tests (floor 497); R-3-078/079 fixed, verified in tree |
| N3-1 | dispatched | `900d36d` | ledger `0be7e8f6d051`, g8 PASS |
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

## N3-T: two contract defects, confirmed in the tree

@redline asked to confirm three assumed endpoint contracts and, across four messages, did not
register the answer — it reported the question outstanding each time while continuing to build
on the assumption. Verified in the tree at `de7831e` rather than by message:

```
grep -rc snapshot_token stage-3/tests/   → test_snapshots.py:14, test_statement.py:5,
                                            invariants/hook.py:11  (35 occurrences)
grep -rn '"snapshot"'  stage-3/tests/    → zero
```

1. **R-3-079 violated.** The token is spelled `snapshot`, not `snapshot_token`. Worse than a
   rename: `hook.py:93` reads `body.get("snapshot_token")`, always `None`, and `hook.py:495`
   guards the whole R-3-005 frozen-pagination invariant on that value, so the check reports
   green having executed nothing. Same shape at `709/759` and `901/904`. The fix is the rename
   **plus** making absence a failure instead of a skip.
2. **R-3-078 violated.** `test_known_at.py` (docstring 15–17, helper 31–32, assertions 47/62/69)
   asserts that `GET /payments/{id}/revisions?known_at=T` filters and 404s before the first
   revision. It does neither: the param is unknown there, so R-1-023 makes it ignored and the
   full list returns 200.
3. The corrections contract and the statement `opening_balance`/`closing_balance`/`entries`
   shape were assumed correctly — no change.

@builder was told to build to R-3-078/079 rather than to those three assertions, so N3-1 was
never blocked on the test fix.

**Resolved at `846862a`, verified in the tree rather than by message:**

- `body.get("snapshot")` at `hook.py:98`, `params={"snapshot": …}` at `:508` and `:930` — the
  wire names are right. The 13 remaining `snapshot_token` strings are local variables and ctx
  keys (`statement_snapshot_token`), which I had explicitly permitted; my "grep must show zero"
  acceptance test was the wrong metric and I withdrew it.
- Fail-closed at `hook.py:504-505`: `/statement` answering 200 with no `snapshot` field now
  returns `False` naming R-3-080. A 404 on `/statement` still skips, which is correct — that
  means unimplemented, and `test_statement.py` fails loudly on it instead.
- Gate 5's upgrade path asserts `snap.status_code == 200` (`hook.py:932`), so it is fail-closed too.
- `test_known_at.py` rewritten: the exclude-not-zero trap now runs against `/me` and
  `/statement`, plus new tests that `/revisions` ignores `known_at` including a malformed value.
- Scope `8dfcc60..HEAD` clean; 573 tests.

**N3-T.1, residual, non-blocking.** `hook.py:511` reads
`if r.status_code == 200 and r.json() != ctx["statement_first_page"]`. A **non-200** on the
snapshot re-fetch therefore passes silently — a service that invalidated or mis-scoped its
tokens would return 404 and the R-3-005 invariant would report green. Same silent-pass class as
the original defect, one layer in. Gate 5's path already asserts 200; gate 4's must too.

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

`stage-3/_restart_server.py` and `stage-3/_server.log` are stage-2 working scratch that the
copy carried forward. **Nothing needs doing about them, and I was wrong to call them a
gate-1 risk.** Verified after @builder's N3-0 report:

- Both are **untracked** (`git ls-files stage-3/` lists neither) — @builder deliberately kept
  them out of `8dfcc60`, as it did on stage 2.
- `stage-3/Dockerfile` copies only `main.py` and `service/` (`COPY main.py ./main.py`,
  `COPY service ./service`), not `COPY . .`, so neither file can reach the image even when a
  gate builds from the working tree rather than a clean worktree. There is no `.dockerignore`
  and none is needed.

So the N3-1 dispatch carries **no** cleanup task for these. Dropping it rather than spending a
builder turn on a non-problem.

**`stage-3/tests/_manual_check_n24b.py` stays.** I originally told @redline to delete it in
the N3-T handoff. That instruction was wrong and is withdrawn: the scope check flags *any*
deleted test under `stage-*/tests/`, whether or not it is a real test, so removing scratch
there would keep every later stage-3 scope range red for no benefit.

## Scope baseline for stage 3

**Stage 3's scope range is `8dfcc60..HEAD`** — i.e. starting after the copy-forward commit.
Recorded per the operator's note of 2026-10-05, which asked that the range start after the
Human commit `11a52eb` (`mandates/planner.md`) and that the reason be stated in the record.
`8dfcc60` is after `11a52eb`, so this satisfies that instruction and also fixes a second
problem:

- `11a52eb` is authored `Human`, outside `factory/`, so any range containing it reports a
  non-seat commit. Excluded by starting later, exactly as was done for `db83d89` in stage 1.
- `8dfcc60` is the `factory.stage_copy` commit (authored Builder, correctly). Because
  `stage_copy` reproduces the whole previous stage folder, it necessarily makes the builder
  the author of files under `stage-3/tests/`, which is @redline's boundary. Run from a base
  *before* the copy-forward, the scope check therefore reports
  `builder edited stage-3/tests/… outside its scope` for every copied test file. **This is
  the structural reason stage 1's and stage 2's scope gates both read `fail` in
  `factory.report --summary`** — not misconduct, an artifact of how a stage starts. Basing
  stage 3 at `8dfcc60` removes it.

Verified: `python -m factory.scope 8dfcc60..HEAD` reports only the one item below.

## Disclosure: a scope violation of mine, stage 3

`2fad7e7` (mine, intended to carry only `plan/lessons.md`) also contains the deletion of
`stage-3/tests/_manual_check_n24b.py` — a file in @redline's boundary. I did not delete it
by hand: @redline had staged the deletion while acting on my (withdrawn) instruction above,
and my `git add plan/lessons.md && git commit` swept the already-staged path in. The scope
check correctly reports `2fad7e716a: planner deleted test stage-3/tests/_manual_check_n24b.py`.

It is mine and it stands on the record. Remedy: @redline restores the file as part of N3-T,
and per FACTORY.md owner-restored paths clear the check. Both root causes are in
`plan/lessons.md`: commit with an explicit pathspec on the commit (`git commit -- <paths>`),
because in a shared tree another seat may have staged work; and never order a deletion under
`stage-*/tests/`.

@verifier: use `--scope 8dfcc60..HEAD` for every stage-3 item and for the stage-3 close.
This range is expected to be clean once @redline's N3-T commit restores that file; if it is
not, the planner violation above is the reason and it is disclosed, not hidden.
