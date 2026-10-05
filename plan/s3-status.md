# Stage 3 status

## >>> LIVE WORK FOR @verifier — read this first <<<

Room messages have been crossing badly, so this block is the authoritative target. It is
updated every time a node becomes gateable. If a message and this file disagree, **this file
wins** — check `git log -1` on it for freshness.

**N3-1 is NEEDS_WORK — do NOT GO on `3f480dc` or on `08caa74`.** @adversary landed a confirmed
BREACH at `0dfd763` and **I have ruled the adversary correct** (R-3-018a, committed in
`plan/s3-requirements.md`). @builder reverted its first fix because the strict check broke three
redline-authored tests and asked me to rule rather than guess — the right call. The ruling is
below; the fix is now re-dispatched to @builder and three test fixtures to @redline.

N3-2 at `08caa74` is otherwise good: **g4 PASSES** — the R-3-016 storm invariant that was
binding for that item — plus scope, g1 and g8 PASS.

**@redline's side is done (N3-T.2, `6435664`).** All three flagged fixtures corrected by raising
the receiver's seeded balance, nothing else changed; it swept the suite and found a **fourth**
instance I had missed (`test_upgrade_stage1_stage2.py::test_import_document_with_no_revisions_key_still_yields_revision_1`);
`demo_fixture.py` verified clean. Three new tests in `test_reset_fixture.py`: the reject side
with a state-unchanged check (`:211`), the accept-at-exactly-zero boundary (`:237`), and the
import-side equivalent (`:254`) built from a **real export** with only the receiver's wallet
balance mutated rather than a hand-authored document. 578 tests, scope clean.

The import-side test reds correctly until R-3-018b is built — that is the one remaining piece of
@builder's strict-check commit, and it is the half I expect to be forgotten.

**@builder's fix at `e481fcd` is HALF DONE — R-3-018a landed, R-3-018b did not.** Verified:

```
grep -rn validate_payment_history_nonnegative stage-3/service/
  revisions.py:85   (definition)
  fixtures.py:16,220  (reset path only)
```

`snapshot.py:273`'s `validate_import_document` never calls it, so an imported state implying a
negative opening balance is still accepted. This is the exact half I predicted would be
forgotten, and @redline's `test_reset_fixture.py:254` is the test that catches it.

**Do not GO on `e481fcd`.** Wait for the import-side commit, then gate N3-1 and N3-2 together
against that sha with `--commit <sha> --scope 8dfcc60..HEAD`.

@adversary persisted the microsecond `as_of` boundary at `49f4bca` and verified it green — that
test now guards @builder's `now_rfc3339()` precision fix, which nothing else covered.

**The BREACH (R-3-018, and it poisons R-3-016/R-3-002):**
`validate_payment_history_nonnegative` in `stage-3/service/revisions.py` computes the opening
balance with `compute_opening_balances(...)` and then only checks negativity **after** replaying
each payment forward — it never checks the opening instant itself, before the loop. So a seeded
payment whose **receiver** has a low or zero ending balance implies a deeply negative balance for
that receiver at the opening instant (ending 0, received 1000 → opening −1000), and the forward
replay masks it: reset returns 204 instead of 422. It also silently stores that negative value in
`opening_balances`, which will surface as a negative historical balance (R-3-002) the moment
`GET /me?as_of=<before the earliest payment>` exists — i.e. as soon as N3-2 lands, and it is
exactly what gate 4's R-3-016 check reads.

When the fix commit is posted, run:

```
python -m factory.gates.run stage-3 --node N3-1 --gates 1,2,4,8 --scope 8dfcc60..HEAD --commit <fix sha>
```

`--commit <sha>` is **mandatory**: @builder has N3-2 uncommitted in the shared tree
(`me.py`, `revisions.py`, `json_utils.py` modified), so gating the working tree would judge
N3-1 against half-built N3-2 code.

Pass/fail per the policy below: binding = `g1`, `g8`, scope. `g2` and `g4` advisory, binding
condition **no regression**. Expected and acceptable at this commit: g2 **528/573** with all 45
failures in `test_corrections*.py`, `test_historical_holds.py`, `test_historical_overdraft.py`,
`test_known_at.py`, `test_me_as_of.py`, `test_snapshots.py`, `test_statement.py` and one import
test; g4 failing **only** on R-3-016, which needs `GET /me?as_of` (N3-2's scope, absent here).
**Anything else failing, or any regression → NEEDS_WORK.**

Review targets: revision 1 must exist for **every** payment including **imported** ones (an
empty `revisions` list after import is the likeliest defect); `revisions.py` is shared by reset
and import so they cannot drift; R-3-064 — a third party gets **404, never 403**, even on a
public payment, and no token is 401.

**Stage 2 is closed PARTIAL and is not reopening.** Nothing is open on it. Do not run any
stage-2 close, and never scope from `4cce19d` — you were right to refuse that.

---

Folder `stage-3/` is the copy-forward of stage 2 at `bc6a8cc` (commit `8dfcc60`).
Stage 3 opens with its own fresh budget: 480 minutes, $120 (`factory/budget.yaml`).

| id | state | commit | evidence |
|---|---|---|---|
| N3-T | **closed** | `0de89ec` | 573 tests (floor 497); R-3-078/079 fixed, N3-T.1 fixed, scope clean |
| N3-1 | NEEDS_WORK — BREACH `0dfd763` | `3f480dc` | R-3-018 opening-instant check missing; fix folds into N3-2 |
| N3-2 | dispatched | `3f480dc` | owns R-3-020+; unblocks N3-1's g4 |
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

**N3-T.1 — fixed at `0de89ec`, and it found a fourth instance.** `hook.py:509` had
`if r.status_code == 200 and r.json() != ctx["statement_first_page"]`, so a **non-200** snapshot
re-fetch fell through to `return True, "ok"` — a service that invalidated, mis-scoped or dropped
its tokens would have passed gate 4's R-3-005 check. Now split into a status check that fails
with status+body naming R-3-082, then the body comparison, matching gate 5's existing
`assert snap.status_code == 200`.

@redline then audited the whole file on its own initiative and found one more of the same class,
**pre-existing from the stage-2 hook**: the holds/captured-amount reconciliation fell back to an
empty `/activity` feed on a non-200, which made the reconciliation vacuously skip rather than
catch a real defect. Also fixed to hard-fail. That was a good catch and not something I asked for.

Verification at `0de89ec`: `grep -n "status_code == 200 and"` over `hook.py` prints **nothing**;
the other ten response checks in the file all use `!= 200`. Scope `8dfcc60..HEAD` clean.

**Four instances of "a check that cannot fail" in one hook** — wrong field name, truthiness
guard, conditional comparison, and the feed fallback. That is why `plan/lessons.md` states the
rule generically: it is the failure mode most likely to let a hidden check through, and it is
invisible to a green test run by construction.

## PLANNER DECISION: which gates bind per item in stage 3

@builder's N3-1 report exposed a sequencing error in my own DAG, and it is mine, not its.
I wrote `plan/s3-dag.md` saying every item runs `--gates 1,2,4,8`, but stage 3's suite and
gate hook were written against the **whole stage**:

- **g2** runs all 573 tests, so every test belonging to a later item fails until that item is
  built. At N3-1: 528/573, and all 45 failures are in `test_corrections*.py`,
  `test_historical_holds.py`, `test_historical_overdraft.py`, `test_known_at.py`,
  `test_me_as_of.py`, `test_snapshots.py`, `test_statement.py` and one import test — every one
  calling an endpoint or query parameter N3-1 does not build.
- **g4**'s `invariant()` checks R-3-016 through `GET /me?as_of=<before earliest payment>`.
  `as_of` is N3-2's scope, and verified absent from `stage-3/service/routes/me.py` today, so
  under R-1-023 it is ignored and the check compares the opening balance against the current
  one. **N3-1's g4 cannot pass no matter how correct N3-1 is.**

Demanding a per-item GO on those two would mean either blocking N3-1 forever or weakening the
hook — and weakening it is exactly the silent-skip failure we removed four times in N3-T. So:

**For every stage-3 item, binding gates are `1`, `8` and the scope check. `g2` and `g4` are
advisory with one binding condition: no test that was green at the previous item may fail, and
no invariant that was passing may break (no regression).** Both become fully binding at the
item that completes their dependency, and unconditionally at stage close (`--gates all`), where
the whole suite and the full hook must pass. This is the same treatment @verifier already
applied in stages 1 and 2, where mid-stage g2 was recorded advisory; I am stating it up front
for stage 3 instead of rediscovering it per item.

Consequence for N3-1: it may close on scope/g1/g8 plus content review, with g2 at 528/573 and
g4 failing **only** on the `as_of` check above. N3-2 is dispatched to remove that cause, and
**g4 becomes binding at N3-2** — if it still fails there for any reason other than a later
item's endpoint, that is a defect.

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
