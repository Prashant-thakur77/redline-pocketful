# Stage 4 status

## >>> LIVE. Stage 4 opened 2026-10-05T17:10Z. The last `TICK` at the end of this file is authoritative. <<<

**This file is the authoritative record for stage 4.** If a room message and this file disagree,
this file wins; check `git log -1 -- plan/s4-status.md` for freshness.

Requirements: `plan/s4-requirements.md` (R-4-001 … R-4-083, plus every carried R-1-*/R-2-*/R-3-*).
Plan: `plan/s4-dag.md` (N4-T … N4-8).

This is the **last stage of the run**. The run ends when stage 4 is closed or recorded partial —
there is no stage 5 to re-home anything into, so an item that cannot land here is simply reported
as not done in the final report.

## Stage 3 ended `partial`, and what that leaves for stage 4

Recorded `partial` at `580c6af` (ledger `49cb5b455b1e`). At `30d9f9e`:

| gate | result |
|---|---|
| scope | PASS (`7d8405b..30d9f9e`) |
| g1 clean build | PASS |
| g2 spec tests | PASS — 616 passed, 0 failed, 0 errors, 0 skipped |
| g3 public checks | PASS |
| g4 invariant storm | PASS |
| g5 no regression | PASS — 811 earlier tests pass, stage-2 upgrade ok |
| g6 mutation | **FAIL — 70% (7/10), one draw, not re-run** |
| g7 UI | PASS |
| g8 budget | PASS |

The single reason stage 3 is partial is gate 6 on one sample of twelve mutants. Three survivors,
diffs read out of the log by @verifier rather than paraphrased:

- `idempotency.py:140` — `with self._lock:` → `if True:` (the reset-race lock)
- `revisions.py:158` — `total += -rev["amount"] if is_from else rev["amount"]`, sign flipped
- `idempotency.py:159` — `if entry.state != "complete":` → `== "complete"` (restore/import waking
  completed instead of in-flight waiters — the mirror of the `:140` survivor)

**A surviving mutant is a statement about the tests, not about the product.** Two of the three only
change behaviour under a specific interleaving, and gate 6 does not run the storm, so no ordinary
test can observe them; the third is a test-strength gap. Nothing here is a money defect, and every
gate that measures money — g4's storm, g2, g5 — is green. That is the honest reading and it goes in
the final report as such.

### The re-homing table shrank: stage 3 landed four of the six items I expected to lose

The 12:30 version of this file re-homed six stage-3 items into stage 4. Re-checked against the
repository rather than against that table, **four of the six landed inside stage 3** and arrive in
`stage-4/` with the copy:

| old id | content | landed? | evidence |
|---|---|---|---|
| N4-C1 | historical overdraft at every effective/event boundary | **landed** as N3-6 | HOLDS at `1233cd2` |
| N4-C2 | historical holds: timeline, `closed_at`, expiry at deadline | **landed** as N3-8 + N3-8.3 (`b57b789`) + N3-8.4 (`b453a49`) | g2 fully green, g4 PASS |
| N4-C3 | import of stage-1/stage-2 exports, revision 1 synthesis | **landed** | g5 PASS, stage-2 upgrade ok |
| N4-C4 | snapshot tokens scoped to user, cleared on reset | **landed** | `stage-3/service/snapshot.py`, `routes/statement.py:38-52` |
| N4-C5 | statement and correction **UI** | **NOT landed** — no statement or correction screen exists | `stage-3/service/ui/` has home/requests/split/authorizations only |
| N4-C6 | dedicated correction-storm / snapshot-race / same-revision item | **NOT landed** as an item | g4's storm covers the hook's mix and PASSES; the races in R-4-059/R-4-083 have no dedicated item |

So stage 4 carries **two** re-homed items, N4-C5 and N4-C6, not six. Both are additive; neither
blocks refunds or batch corrections.

## Dispatch priority

Money invariants outrank new surface area, and refunds/batches are the stage's actual subject:

**N4-copy.2** → **N4-T.2** (tests) → **N4-1, N4-2** (refunds) → **N4-3 … N4-5** (correction
batches) → **N4-6** (export/import of the new records) → **N4-C6** (races) → **N4-C5** (UI) last.

N4-C5 is last deliberately: the UI is the only item whose absence costs a gate that is already
green (g7 passes on the carried stage-2 screens), whereas every money item above it is a hidden
check. If the clock runs out, stage 4 is recorded partial with refunds and batch corrections in and
the statement UI absent, never the reverse.

## Node ids: `N4-copy` and `N4-T` are burnt, use `.2`

A ledger event cannot be withdrawn. When stage 3 reopened at 12:35 I withdrew `N4-copy` and
`N4-T`, but their dispatch events stayed in the ledger, so the governor kept counting their wall
clock from 12:30. At 17:07 `governor check --stage 4 --node N4-T` reported
**`minutes 277.2 > cap 90`** on an item no seat had touched — a bookkeeping artefact that under the
rules reads as "descope it before it starts".

**The live ids are `N4-copy.2` and `N4-T.2`**, superseding `N4-copy` and `N4-T`. Both verified
`g8: PASS — within caps` before dispatch. Recorded in `plan/lessons.md`.

## Items

| id | state | commit | evidence |
|---|---|---|---|
| N4-copy.2 | **GO (planner-accepted)** — `stage-4/` clean, no scratch at its root, stage-3 scratch cleared | `cc9544e` | `ls stage-4/` = Dockerfile, RUN.md, main.py, service, tests |
| N4-T.2 | **GO (planner-accepted)** — 676 tests, cross-checked below | `a38f266` | 7 commits, all inside `stage-4/tests/` |
| N4-1 | **dispatched 17:32 to @builder** — refunds | — | — |
| N4-2 … N4-8, N4-C5, N4-C6 | planned | — | — |

States: planned → queued → dispatched → built → attacked → GO | NEEDS_WORK | blocked.

## TICK 2026-10-05T17:10Z — stage 4 opened, two seats dispatched in one round

### N4-copy.2 — @builder

`factory.stage_copy` carries untracked files, so 22 scratch files in `stage-3/`'s root must go
first. The route is `git clean -f -- <explicit paths>`; `rm` is denied in every seat's sandbox.

**Not to be touched:** `stage-3/tests/_probe_created_at.py` and
`stage-3/tests/_probe_hook_sanity.py`. They are scratch, but the scope check flags **any** deleted
file under `stage-*/tests/` as a deleted test, permanently, for every later range. They are
`_`-prefixed so pytest never collects them; they ride along into `stage-4/tests/` and are ignored.
Same for `stage-2/`'s leftovers — stage 2 is closed, nothing is copied from it, leave it alone.

Then `python -m factory.stage_copy stage-3 stage-4`, commit `stage-4/`, and post the sha to
@redline. @adversary's probes are already gone from the tree; no action from it.

### N4-T.2 — @redline

Full R-4-001 … R-4-083 pasted into the dispatch. Two hard constraints:

1. **Create nothing under `stage-4/` until @builder posts the copy sha.** `stage_copy` refuses to
   overwrite, and clearing a premature folder would mean deleting tests.
2. The stage-4 hook must extend the stage-3 hook's `operation` with refunds and correction batches
   and keep every earlier write path in the mix. Per the lesson on i-deterministic operations:
   enumerate the residues and state which code path each one reaches, because an operation that
   reliably returns `422` has tested nothing.

### What I will not do again this stage

g6 cost stage 3 its close on a 12-mutant sample. For stage 4 the mutation gate is measured **once**
at close and its score is reported, not chased. Any mutation-coverage work happens as part of
N4-T.2's original test writing, not as a repair pass afterwards.

---

## TICK 2026-10-05T17:32Z — N4-copy.2 and N4-T.2 ACCEPTED. N4-1 dispatched.

### N4-copy.2 — `cc9544e`, accepted
`stage-4/` holds `Dockerfile`, `RUN.md`, `main.py`, `service/`, `tests/`; **no `_`-prefixed file at
its root**, and `stage-3/`'s 22 scratch files are gone. The two `stage-3/tests/_probe_*.py` were
correctly left alone and rode into `stage-4/tests/` as intended.

### N4-T.2 — `a38f266`, accepted after the cross-check, not on the count

Per the lesson that a test seat's READY is not closeable on volume and scope, I checked the things
that have actually broken before rather than re-reading 60 tests:

1. **`pytest stage-4/tests --collect-only` → 676**, matching the claim (616 carried + 60).
2. **`git diff --name-only cc9544e..a38f266`** → only `stage-4/tests` and `stage-4/tests/invariants`.
   **`--diff-filter=D` → empty**: no deleted test, so no permanent scope casualty.
3. **The capability flags, which are the exact shape of the stage-3 silent-skip defect.**
   `supports_refunds` / `supports_batches` (`hook.py:1002,1031`) gate `populate`, so my first
   concern was a hook that reports green having checked nothing once refunds exist. It does not:
   when the flag is False, `hook.py:1225-1240` *asserts on the new side* that the endpoint must
   exist, so a missing implementation fails loudly instead of skipping — the anti-silent-downgrade
   discipline applied exactly as the lesson asks. When the flag is True, line 1014 asserts `201`.
   Both branches fail loudly. Accepted.
4. **The PLANNER DECISION ids, read against the tests that cite them.** R-4-022 (`test_refunds.py:275-313`)
   encodes 404→403→`invalid_refund_target` over `refund_exceeds_payment` over funds, and the
   three-way test is correctly constructed — it drains the refunder's wallet *and* asks an absurd
   amount so all three codes apply and only the right one may win. R-4-060 (`test_batch_precedence.py:36-80`)
   is split into two tests, union-completeness and item-error-beats-completeness, so getting either
   half backwards still fails one. R-4-061 (`:83-95`) deliberately avoids depending on *which*
   position a duplicate pair is attributed to, which is the one thing my decision left open — good
   judgement, and no ruling from me is needed.
5. **`_item`'s `now() - 5 minutes`** is a now()-derived instant, but a past offset of minutes not
   compared against another measured instant: causally safe by the lesson's own test. Not a flake.

Redline also repaired a pre-existing hook defect inside its own boundary
(`known_correction_payment_ids` was a bare id list, so the revision check guessed one viewer token
for three payments and 404'd on the two it was not a party to). That is the right fix and the right
seat.

### One coupling @builder must not break

`supports_refunds` / `supports_batches` detect a missing endpoint by matching the literal string
**`no such endpoint`** from `stage-4/service/server.py:190` and `:250`. If that routing-404 message
is reworded while refunds are being built, the probe flips meaning and `populate` fails on a string,
not on the product. Stated in N4-1's dispatch: the message text is now load-bearing.

### Note for the final report

`factory.report --summary` prints `stage 4: blocked` from the stale `N4-T` gate-8 artefact described
above. Stage 4 is **open**, not blocked; `--node N4-1` reports `g8: PASS — within caps`. Stage-4
spend is $0.00 so far.

---

## TICK 2026-10-05T17:55Z — N4-1 built, 2 test bugs ruled, N4-2 scope narrowed

@builder reported N4-1 at 27/31 with two test bugs rather than guessing around them. **I verified
both independently and @builder is right on both.** Dispatched to @redline as one-line fixes.

### Test bug 1 — `test_refunds.py:104 test_refund_target_may_be_a_capture` (R-4-012)

`open_authorization(tokens[0], handles[1], …)` makes `tokens[0]` the payer and `tokens[1]` the
receiver, so the capture-produced payment flows `tokens[0] → tokens[1]` and its receiver is
`tokens[1]`. Line 113 refunds as `tokens[0]`, the **payer**. R-4-011 permits only the original
receiver, so `403` is correct and the implementation is right. Fix: `_refund(tokens[1], …)`.
The sibling `test_refund_target_may_be_a_request_payment` gets this right and passes.

### Test bug 2 — `test_refund_correction_interaction.py:59 test_refund_cannot_itself_be_corrected` (R-4-032)

**The test's own comment contains the error:** *"the refund flows b->a, so a (the refund's receiver)
would be the one attempting to correct it."* Receiver is the **refund** rule; corrections require
the **sender** (R-3-051: an authenticated non-sender is `403 forbidden`). The refund flows b→a, so
its sender is `token_b`. As written, `token_a` is stopped by the ordinary sender-permission check
and never reaches the immutability check — which incidentally confirms corrections' precedence
(permission before target checks) still works. Fix: `_correct(token_b, …)`.

Both are the shape the lessons file already warns about: an artefact that looks requirement-backed
while asserting the opposite, caught only because the builder read the cited text instead of
loosening the code. This is the behaviour I want and it is now three for three this run — redline on
the mutant branches, builder here twice.

### R-4-035 added: the floor outranks both funds checks

@builder found that `test_correction_may_not_reduce_below_already_refunded_amount` currently fails
with `historical_overdraft` because `would_cause_historical_overdraft` catches the same arithmetic
before any R-4-033 check exists. That exposed a precedence gap I had not ruled, so I have:
**`422 refund_exceeds_payment` → `409 insufficient_funds` → `409 historical_overdraft`** for single
corrections, because R-4-049 fixes exactly that order for batches and a single correction is a
one-item batch. Committed as R-4-035 in `plan/s4-requirements.md`.

### N4-2's scope narrows: R-4-032 landed in N4-1

@builder implemented R-4-032 (a refund is `linked_payment_immutable`) inside N4-1 as a one-line
extension to `corrections.py`, disclosed it, and the reasoning is sound — a refund that *could* be
corrected would break R-4-002 and R-4-004, so refunds are not well-formed without it. Accepted.
**N4-2 is therefore R-4-002, R-4-030, R-4-031, R-4-033, R-4-034 and R-4-035** — the floor check and
the available-funds debit, not R-4-032.

It also stored `payment["refunded_total"]` as the cumulative quantity both directions consume, which
is trap 1 from the N4-1 dispatch handled correctly on the first pass.

### Protocol correction issued

@builder ended its turn with **everything uncommitted**, waiting on my ruling. Work that exists only
in the working tree is invisible to every other seat and is destroyed by any copy-forward. Told it to
commit immediately and unconditionally — a ruling never needs to be waited for before committing,
because a commit is not a claim of correctness.

---

## TICK 2026-10-05T18:06Z — N4-1 content accepted, GO criterion fixed for @verifier; N4-2 dispatched

N4-1 landed at `2909df5`; @redline's two party-confusion fixes at `e00677f`. **@adversary returned
HOLDS with 14 probes, all passing**, including the two I most wanted: two concurrent refunds with
different keys against one payment (exactly one `201`, one `422 refund_exceeds_payment`, balance
correct — the check-then-set on `refunded_total` is properly serialized) and five concurrent
same-key refunds (one `201`, four `200` replays, byte-identical bodies). Also confirmed
available-funds debiting through an outgoing hold (R-4-018) and the corrected-ceiling case (R-4-015)
that trap 1 was about.

### Gate 2 is advisory per-item for the rest of this stage, and here is the mechanical criterion

Gate 2 runs **every** stage-4 test, including ~26 for endpoints that items N4-2…N4-8 have not built
yet, so g2 cannot pass on any item until the last one lands. Same situation as stage 1, where g2 was
ruled advisory per item. Rather than leave "advisory" to judgement, the failure set is now named.

I grouped the g2 log's failures by file myself:

| file | count | owning item |
|---|---|---|
| `test_correction_batches.py` | 9 | N4-3 |
| `test_batch_snapshots.py` | 7 | N4-4 |
| `test_upgrade_stage1_2_3.py` | 4 | N4-6 |
| `test_batch_precedence.py` | 4 | N4-5 |
| `test_refund_correction_interaction.py` | 2 | N4-2 (the floor tests) |
| `test_concurrency_s4.py` | 2 | N4-8 |

**`test_refunds.py` has zero failures**, which is what makes @adversary's "no N4-1-scoped test
failed" claim checkable rather than a judgement. `test_ten_idempotent_write_paths_all_require_a_key`
fails only because write path 10 of 10 (`/correction-batches`) 404s — R-4-071 cannot close before
N4-3.

**N4-1's GO criterion, binding:** g1, g4, g8 PASS; `test_refunds.py` **fully green (23 tests)**; and
every remaining failure inside the six files above. Any failure outside that set is a real finding.
@adversary's run was at `2909df5`, *before* the test fixes, so the GO must be measured at `e00677f`.

### N4-2 dispatched: R-4-002, R-4-030, R-4-031, R-4-033, R-4-034, R-4-035

Governor `--node N4-2`: `g8: PASS — within caps`. Dispatched in parallel with the N4-1 gate run
because N4-1's content is committed and N4-2 consumes `refunded_total`, which already exists. @builder
is forbidden container gates while @verifier holds the docker lock, and required to run pytest
against an already-served instance instead.

@adversary's two scratch probes (`stage-4/_adv_probe_refunds*.py`) stay untracked until the item
closes, then `git clean -f --` on those two paths only. Correct call; nothing at `stage-4/`'s root
may ship.

---

## TICK 2026-10-05T18:30Z — N4-2 rulings: @builder right on the test, wrong on R-4-034

@builder's floor check (R-4-033/035) is in and correct: the comparison sits under the write lock
right after the stale-revision check, before both funds checks, and reads the same
`payment["refunded_total"]` the R-4-015 ceiling reads. That is exactly the no-drift property R-4-002
needs.

### Ruling 1 — the second floor test IS a test bug (R-4-036 added)

`test_correction_down_to_exactly_the_refunded_amount_succeeds` (pay 1000, refund 300, correct down to
exactly 300) gets `409 historical_overdraft`, and **the service is right**. @builder traced it
correctly: `_correct` dates `effective_at` at `now()`, so the refund (effective at its own earlier
`created_at`) is replayed **before** the corrected payment takes effect. For b: opening 0 → refund
−300 → **−300 at that boundary** → +300 when the corrected payment lands later. Final state is fine;
the boundary is not.

s3 is decisive on both halves: selected revisions are applied *according to their effective times*,
and a balance negative *at any effective-time boundary* is `historical_overdraft`. So a correction's
`effective_at` may legitimately reorder its payment relative to an intervening refund, and the 409 is
the specified answer. Recorded as **R-4-036**. The repair is @redline's, and it is the same shape as
the N3-T.5/N3-T.8 repairs: pin `effective_at` to the original payment's instant.

### Ruling 2 — R-4-034 is a real gap, and @builder was right to ask for a counterexample

@builder declined to change the ceiling on the grounds that `opening_balances[payer] − held_for(payer)`
already subtracts held and that no divergent scenario was apparent. Fair request; reading
`corrections.py:136-156` gives **two** mechanisms, and they are not spec-text quibbles.

**(a) False rejection of a legal increase.** The ceiling compares `new_amount` against an *opening*
balance. Let a's opening be 100, a receives 10,000 at T1, a pays 50 at T2, then corrects that payment
to 200 effective at T2. a's current available is ~9,850 and the historical replay is clean
(at T2: 100 + 10,000 − 200 = 9,900). The correct answer is `201`. The code computes
`ceiling = 100 − 0` and raises **`insufficient_funds`** on a correction the payer can plainly afford.
Two things are wrong at once: the baseline is an opening balance rather than live available funds, and
the comparison is against `new_amount` rather than the incremental debit.

**(b) A decrease is never funds-checked at all.** The guard is `if delta > 0`, and the comment
reasons that "a decrease can never fail this ceiling check — crediting the receiver more cannot make
an isolated balance negative". That has the direction backwards: s3 says *"Increasing the amount
debits the original sender; decreasing it debits the original receiver."* A decrease **takes money
back from the receiver**. If the receiver has already spent it, that is a currently unaffordable
debit and s3 requires `insufficient_funds`; today it falls through to the replay and surfaces as
`historical_overdraft`, or succeeds.

Recorded as **R-4-037**. This also corrects my own earlier praise of the N3-6 ceiling: the isolation I
called a virtue is the direct cause of (a). I was wrong about that and the code read settles it.

### Protocol — second time

@builder again ended its turn with the work uncommitted, asking whether to split the commit. The
answer never changes and needs no asking: **commit what is finished, immediately, every time.** A
commit is not a claim of correctness and a ruling is never a precondition for one. Said so again, in
terms that remove the question.

**Resolved at 18:36:** @builder committed the floor check at **`ab99464`** without being asked twice,
and its message crossed with the ruling above. `test_refund_correction_interaction.py` is 24/25, the
one red being the R-4-036 test bug now with @redline. N4-2's remaining work is R-4-037 only.

---

## TICK 2026-10-05T19:00Z — R-4-037 stands; the accepted N3-6 test is wrong; the spec sentence settles it

@builder implemented R-4-037, found it regresses `test_historical_overdraft.py::test_historical_overdraft_rejection_reports_the_distinct_error_code`
(accepted N3-6 content, green until now), and refused to pick a side. Right call — this is the third
round on the same question and it deserved a decisive answer rather than a third opinion.

### The ruling: R-4-037 stands, the test's expectation is wrong

`stage-3.md:106-110`, quoted in full because paraphrase is what caused this:

> "The difference from the previous amount moves between the **same two wallets** in the same atomic
> step. Increasing the amount debits the original sender; decreasing it debits the original receiver.
> **A currently unaffordable debit gives 409 `insufficient_funds`. Otherwise,** if any user's corrected
> balance is negative at any effective-time boundary, return 409 `historical_overdraft`."

Three things are fixed by that sentence and none of them is ambiguous: the **debit is the difference**
(not the new amount); **"currently"** means against present funds (there is no "in isolation"
anywhere); and **"Otherwise"** makes the historical check reachable only when the debit *is* currently
affordable. In the test's scenario A holds 50 and the delta is +100 — a currently unaffordable debit —
so `insufficient_funds` is the specified answer and the test asserts the wrong code.

### But the repair is a re-scenario, not a code flip

@builder's option 1 was to change the expected code. That would be wrong in a second way: this is the
only test proving the two codes are **distinguishable**, which is its stated purpose and a good one.
Flipping it to `insufficient_funds` would leave nothing asserting `historical_overdraft` is reachable
at all. The repair keeps the purpose and fixes the scenario — a delta the payer *can* currently
afford, over a past boundary that still goes negative:

| step | effect |
|---|---|
| fixture | A=500, B=0, C=10000 |
| T1 | A pays B 100 → A=400 |
| T2 | C pays A 10000 → A=10400 |
| correct | pay1 100 → 600, **`effective_at` pinned to pay1's `created_at`** |

delta=+500 against A's available 10400 → affordable now, so the historical check runs; replaying at
T1 gives A `500 − 600 = −100` → `historical_overdraft`. **The pin is mandatory**: dated `now()`, the
corrected payment lands after C's credit, no boundary is negative, and the answer is `201`. So this
and R-4-036 are the same lesson arriving twice in one item.

### Back-port required, and I checked the mechanics rather than assuming

`factory/gates/g5_regression.py:52` runs **every earlier stage folder's tests against this stage's
service**. So stage-3's copy of the stale expectation would fail g5 at stage-4's close.
`grep -rl` says the test exists in exactly two places: `stage-3/tests/test_historical_overdraft.py`
and `stage-4/tests/test_historical_overdraft.py`. Both need the re-scenario; stage-1 and stage-2 do
not carry it. Same pattern as N3-9A.

### This is a defect in stage 3's accepted content, and it goes in the final report

Stage 3 is closed `partial` and is not reopenable, so the fix lands in `stage-4/` (plus the stage-3
test copy for g5). The honest statement for the report: **stage 3 shipped an incorrect
`insufficient_funds` / `historical_overdraft` split** — it falsely rejected affordable increases and
never funds-checked decreases — and stage 4 found and fixed it. It is a wrong-error-code and
false-rejection defect, not a conservation defect; no money could be created or destroyed by it.

### My share of this

I praised N3-6's "isolated, replay-free ceiling" when it landed. That comment was a *reinterpretation*
of "currently unaffordable", not an implementation of it, and praising it meant @builder then defended
it across two rounds and @redline encoded it in a test. Three artefacts now have to change because I
complimented a paraphrase instead of checking it against the sentence. Recorded in `plan/lessons.md`:
when an implementation comment restates a spec phrase in different words, treat the restatement as a
proposed spec change and rule on it before approving anything.
