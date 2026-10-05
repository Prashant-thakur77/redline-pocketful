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

**Resolved at 19:10:** R-4-037 landed at **`14f5fc0`**, committed with the known red disclosed in the
commit message — correct behaviour. @builder's message crossed the ruling a second time and re-reported
the regression as unresolved; it is resolved (the test is wrong, @redline owns it). **N4-2's build is
complete** at `ab99464` + `14f5fc0`, pending @redline's test re-scenario and @verifier's GO. Told
@builder not to report on N4-2 again.

Second crossing in two rounds from the same seat, both because a ruling and a report were in flight
together. Mitigation applied: every ruling now leads with the resolved/unresolved verdict in the first
line, before the reasoning, so a seat skimming a crossed message gets the actionable bit first.

### N4-3 dispatched

Governor `--node N4-3`: `g8: PASS — within caps`. Stage-4 gates now standing at g1 PASS, g4 PASS,
g8 PASS, scope PASS, g2 advisory-fail (later items' endpoints) — @verifier's N4-1 run has landed its
container gates. Spend still $0.00 recorded against stage 4.

---

## TICK 2026-10-05T19:25Z — N4-1 CLOSED. Scope base corrected to `cc9544e`. N4-2+N4-3 to gate together.

### N4-1 is closed — GO on the named criterion

@verifier met all four parts at `c18a18e` and, better, **confirmed part 3 by file rather than by
count**: all 25 g2 failures land inside exactly the six named files (`test_batch_precedence` 4,
`test_batch_snapshots` 7, `test_concurrency_s4` 1, `test_correction_batches` 9,
`test_refund_correction_interaction` 2, `test_upgrade_stage1_2_3` 2), zero outside. g1, g4, g8 PASS.
`test_refunds.py` fully green. On the point I flagged for scepticism:
`test_refund_target_may_be_a_capture` is **not** in the failing set, so @redline's fix at `e00677f`
holds and independently corroborates @adversary's probe 11.

**Ledger reads HOLDS, not GO, and that is correct.** `factory.record` refuses a GO the gate results do
not back, and g2's raw exit is 1. The GO is the planner's, recorded here against the published
criterion; the ledger's HOLDS is the honest machine record. Worth stating plainly in the final report
so the two are not read as a contradiction.

### Stage 4's scope base is `cc9544e`, not `7d8405b` — @verifier's correction, and it is right

`--scope 7d8405b..c18a18e` FAILS on `cc9544e: builder edited stage-4/tests/_probe_created_at.py
outside its scope`. That commit is `N4-copy.2`, the copy-forward, and the violation is structural, not
behavioural: `stage_copy` makes @builder the author of **everything** under the new folder's `tests/`,
including the two stage-3 scratch probes we deliberately left in place. Re-run at
`cc9544e..c18a18e`: clean.

**Adopted: every stage-4 scope check runs `cc9544e..<tip>`**, exactly as `7d8405b` served stage 3
after its resume. This is a property of copy-forward itself and will recur at any future stage boundary.

### @redline's N4-2 test work went past the brief, in the right direction — `57453e6`

I asked for the N3-6 test to be re-scenarioed so it still proves the two codes are distinguishable.
@redline did that **and** kept the original scenario as a second test,
`test_historical_overdraft_vs_insufficient_funds_currently_unaffordable_debit`, asserting
`insufficient_funds`. So both directions of the distinction are now pinned instead of one, which is
strictly better than what I specified. The back-port landed too: `stage-3/tests/test_historical_overdraft.py`
and `stage-4/tests/test_historical_overdraft.py`, plus `test_refund_correction_interaction.py`.

### N4-2 and N4-3 gate together, with gate 5 included

`14f5fc0` (N4-2), `571aec7` (N4-3) and `57453e6` (tests) are all in. One run rather than two saves a
docker build cycle on the last stage's clock. **Gate 5 is in this run for the first time since the
copy**, because @redline edited `stage-3/tests/` and `g5_regression.py:52` runs earlier folders' tests
against *this* stage's service — that back-port is exactly what g5 exists to check.

### The ledger cannot record a GO yet, and the reason is a stale scope result

`factory.record verdict --verdict GO` for N4-1 was **refused**, as designed:

```
refusing GO: gate g2 last failed: 651 passed, 25 failed; gate scope last failed:
cc9544eb75: builder edited stage-4/tests/_probe_created_at.py outside its scope
```

Two different things there, and only one is expected. g2's advisory failure is known and ruled. But
**the scope entry is stale** — it is the run at the *wrong* base (`7d8485b..`), and @verifier's
corrected run at `cc9544e..` was clean. `factory.record` reads the *last* recorded result per gate, so
until a scope check **passes** and is recorded, no GO can be written to the ledger for the rest of
stage 4.

So N4-1's machine record stays @verifier's HOLDS (`b24fa59102b3`) and the GO is the planner's, here,
against the published criterion. To stop this compounding, **every stage-4 gate run from now on passes
`--scope cc9544e..<tip>`**, so the last recorded scope result is a pass and later items can close in
the ledger as well as in this file. Included in the N4-2+N4-3 dispatch.

---

## TICK 2026-10-05T19:35Z — my test dispatch was stale on arrival; N4-H to @redline

**My R-4-036/037 test dispatch had already been done** at `57453e6`, and @redline proved containment
with `git merge-base --is-ancestor 91fcc2c 57453e6` rather than asserting it. It delivered everything I
asked plus three things I did not specify: the original scenario kept as its own test instead of
flipped, a sweep of all six stage-4 files for the same shape (no other instances), and an R-4-037
decrease-direction counterexample. Item closed; nothing further from @redline on it.

**Third crossing this stage, same cause every time:** I dispatch from the tip I read when I *started
composing*, and the seat has moved past it by the time the message lands. Two fixes from here —
resolve the tip immediately **before sending**, not before writing; and when a dispatch might repeat
work already done, say so in the first line so the seat can answer "already done" cheaply instead of
reading the whole thing.

### N4-H dispatched to @redline — verify the hook against the real implementations

The hook's `supports_refunds` / `supports_batches` probes resolved **False** when @redline validated
them, because neither endpoint existed. Both exist now (`14f5fc0`, `571aec7`), so the refund and batch
slices of `operation()` and the new branches of `populate`/`snapshot`/`carry` are about to execute for
the first time **inside gate 4 and gate 5 at stage close** — the two most expensive gates to fail.
Verifying them now against a served instance converts a stage-close failure into a cheap fix. Also asks
for the residue table to be confirmed **empirically** rather than by construction: count statuses per
residue and show each one reaches the path it was designed for. The batch slice can only be partly
verified until N4-4 lands the commit semantics, so it is re-checked then.

---

## TICK 2026-10-06T00:05Z — N4-2 HOLDS; a flaky UI test is a real close risk; N4-4 dispatched

### N4-2 HOLDS from @adversary — six boundary probes, all passing

The two I most wanted are both exact-boundary cases: a correction to **exactly** the refunded total
returns `201` (R-4-033's floor is "not below", not "strictly above") and one minus that returns `422
refund_exceeds_payment`. Plus the R-4-037 decrease direction at the boundary in both directions
(available funds exactly equal to the give-back → `201`; one short → `409 insufficient_funds`), a
refund-vs-correction race that held conservation and rejected the loser coherently, and R-4-035's
precedence confirmed where both violations apply at once.

**@adversary caught itself almost filing a false BREACH** against a `gates.serve` instance left running
from the N4-1 pass, i.e. pre-N4-2 code, and logged the generic cause itself. That is exactly the
self-check I want from an attack seat, and the near-miss is more useful recorded than hidden.

### The flaky UI test is a construction defect, not "Playwright timing"

@adversary characterised `test_ui_wallet_pay.py::test_changing_a_field_creates_a_new_payment` as
"flaky; UI/Playwright timing, not a corrections.py regression". The second half is right; the first
half understates it. Reading `test_ui_wallet_pay.py:167-185`, the mechanism is **two
`page.wait_for_timeout(500)` calls**: a fixed 500 ms sleep covering a submit whose completion the next
step depends on. Under the load of a full 676-test g2 run, 500 ms is not a guarantee of anything. This
is the same root cause as four earlier test-construction defects this run — an outcome decided by a
wall-clock margin rather than an observed condition.

Counted across the UI suite: **19 fixed sleeps** —
`test_ui_wallet_pay.py` 12, `test_ui_requests_split_authz.py` 3, `test_ui_layout.py` 3,
`test_ui_activity.py` 1, `test_ui_auth.py` 0.

**Why this matters more than it looks:** g2 must be green at stage close, and g7 runs the UI gate. If
any of those 19 can lose its race under load, the stage close is partly a coin flip — and stage 3 died
at its close gate, not in its items.

**Why I am not rewriting all 19.** These tests passed through stage 2's and stage 3's closes, so the
flake rate is low rather than catastrophic, and this is the last stage's clock. Proportionate scope,
queued as **N4-H2** behind N4-H: characterise the known flake over N runs, fix that one with a
condition-based wait, then triage the other 18 into *covers a write the next step depends on* (fix) and
*pads a read* (leave), reporting both counts. Not a wholesale rewrite.

### The other residual failure is N4-6, as expected

`test_upgrade_stage1_2_3.py::test_settlement_membership_corrections_and_snapshots_survive_import`
reproduces consistently and was already in N4-1's failure list; `corrections.py`'s changes do not touch
settlement, import or snapshot paths. It closes with N4-6.

### N4-4 dispatched

Governor `--node N4-4`: `g8: PASS — within caps`. N4-3's code is in at `571aec7`, so commit semantics
can start while @verifier's combined N4-2+N4-3 run is in flight.

---

## TICK 2026-10-06T00:30Z — N4-H found a real R-4-070 defect. N4-6 dispatched as the priority item.

### The finding: snapshot tokens do not survive export/import

@redline's N4-H verification caught a genuine product defect, and I confirmed the **mechanism**
structurally rather than accepting the symptom:

```
grep -n statement_snapshots stage-4/service/snapshot.py   ->  (no matches)
grep -n statement_snapshots stage-4/service/store.py      ->  41 (declared), 98, 139 (cleared)
```

`statement_snapshots` lives in the store but appears **nowhere in the export/import module**. The
export document never carries tokens, so import always lands a fresh empty dict. That is exactly
R-4-070's "retaining settlement membership, corrections **and snapshots**", and it is a clean
violation.

@redline's isolation was good: the token works right up to the import call and 404s immediately after,
while auth tokens, balances, requests, activity, settlement membership, authorizations, capture replay,
correction revisions and correction replay identity all survive the same round trip. So it is
specifically snapshots, not a broken export. Both the general R-3-005/080 token and the R-4-057
pre-batch token break identically.

**It is already covered by a committed test** —
`test_upgrade_stage1_2_3.py::test_settlement_membership_corrections_and_snapshots_survive_import` —
which is the one residual failure @adversary attributed to N4-6 scope two ticks ago. It was a real
defect all along, correctly parked rather than dismissed. **Gate 5 will hit this at close**, so it
blocks the stage.

### N4-H closed with no hook change, which is the right answer

The flags both resolve `True`, `populate()` completes with every branch taken including the
`assert refund_resp.status_code == 201`, and the residue table is confirmed **empirically** over three
independent 2000-op runs: refund residues 0 and 1 are 100% exact (21/21 403, 26/26 422), batch residues
0 and 1 are 100% exact (18/18 409, 15/15 404), and residues 2–9 reach the real path as their dominant
outcome with the remainder explained by genuine concurrent ceiling depletion and replay races.

**@redline found and fixed a bug in its own measurement script** before reporting: it attributed every
`i % 37 == 0` to a refund dispatch, but `operation()`'s cascade tests `i % 29` and `i % 31` first
(`hook.py:394-401`), so composite `i` never reaches `_refund_op`. The first pass's residue-0 anomaly was
that bug, not the service. Catching an instrument error before blaming the instrument's subject is the
behaviour the residue request existed to get.

### N4-4 landed at `f16dd5e` while my dispatch was in flight

So the "commit semantics are N4-4, not yours" scope limit in that dispatch was moot on arrival — a
fourth crossing, same cause. @redline independently verified the three things I flagged as traps:
`correction_batch_id` set on batch revisions and null on single ones, a batch's shared `recorded_at`
strictly later than the prior revision's, and batch replay returning an identical body. All three pass,
and `test_batch_snapshots.py` + `test_correction_batches.py` + `test_batch_precedence.py` (23 tests)
run clean. N4-4 still needs @adversary and @verifier.

### Priority change: N4-6 now, ahead of N4-5

N4-6 was scheduled after N4-5. Moving it up because this defect **blocks the stage close** through gate
5, while N4-5 (batch error precedence) only turns `test_batch_precedence.py` fully green. A close
blocker outranks a coverage gain. Governor `--node N4-6`: `g8: PASS — within caps`.

---

## TICK 2026-10-06T00:50Z — N4-H2 done; 11 same-shape sleeps authorised as N4-H3

### My count was wrong

@redline reports **17** remaining sleeps, not the 18 I stated. It is right: the flaky test contained
**two** `wait_for_timeout(500)` calls and it fixed both, so 19 − 2 = 17. I had subtracted one.

The fix is better than what I asked for. Instead of a longer sleep it waits on
`page.wait_for_function()` polling the balance change — the completion signal **R-2-153 already
guarantees** — so it resolves as soon as the write lands, making the tests faster as well as
deterministic. 5/5 before the fix and 5/5 after; all four UI files (38 tests) green.

**On that 5/5-before result:** @redline drew the right conclusion rather than the convenient one. A
margin-based race need not fail every run to be real, and a fixed sleep covering an unbounded-latency
write is visibly wrong regardless of one run's luck. It did not use its own passing runs to argue
@adversary's finding away, which is the trap that framing invites.

### The triage, and why I am now authorising the 11

| bucket | count | lines |
|---|---|---|
| covers a write the next step depends on — **same race shape** | 11 | `test_ui_wallet_pay.py` 81, 139, 155, 160, 199, 220, 252, 263; `test_ui_requests_split_authz.py` 70, 138; `test_ui_layout.py` 142 |
| pads a client-side read, no server write | 3 | `test_ui_wallet_pay.py` 100, 125; `test_ui_requests_split_authz.py` 56 |
| **deliberate** timing construction, not a guess | 3 | `test_ui_layout.py:163` (route-handler network delay — R-2-154's own mechanism), `:175` (bounds a controlled race against that delay), `test_ui_activity.py:65` (spaces wall-clock seconds to dodge R-2-132's same-second tie) |

The third bucket is the valuable part of the judgement: those three *look* like the defect and are not —
they are the mechanism the requirement itself describes. A blanket "replace every `wait_for_timeout`"
order would have broken them, which is exactly why I asked for triage rather than a rewrite.

### Reversing my own "not all 19" call, on a reason that did not exist when I made it

I scoped N4-H2 narrowly because of the last stage's clock. But the clock constraint is on **@builder's
serial chain** (N4-6 in flight, then N4-5, N4-7, N4-8) — @redline has no item competing with it, so this
is free parallelism rather than work traded against a money item. The pattern is now proven and
mechanical, the 11 are the same shape, and the risk removed is a coin-flip stage close. Cost
reconsidered, the answer changes. Dispatched as **N4-H3**.

Second, smaller part of N4-H3, grounded in stage 3's actual cause of death: g6 is measured once at
stage 4's close, and mutation strength is bought when tests are written. Bounded request — for the
stage-4-new test files only, confirm each test asserts at least one **computed monetary value**
(`balance_after`, `closing_balance`, a resulting balance), not only a status code. A status-code
assertion survives most arithmetic mutations; stage 3's `revisions.py:158` survivor is exactly that.

---

## TICK 2026-10-06T01:10Z — N4-5 is NOT satisfied. @builder's own comment names the gap.

@builder reported N4-5 "already satisfied, nothing to commit", on 15/15 across
`test_batch_precedence.py` and `test_correction_batches.py`. **Three of the four stages genuinely are
built, and I verified the one that mattered** rather than taking the counts:
`correction_batches.py:212-219` accumulates `net[payer] -= delta; net[payee] += delta` across every
item and only then checks `available_for(user) + user_delta < 0`. That is a real combined check, not a
per-item check with extra steps, so R-4-050's current-funds half and R-4-051 are correct.

**But the fourth stage is not, and @builder's own source says so**, at
`correction_batches.py:221-224`:

> `# Stage 4: historical boundaries, per item -- reusing the single-correction primitive. A true`
> `# cross-item historical merge (accounting for every OTHER item's candidate amount at once) is`
> `# not built here; no test in this item exercises it.`

R-4-049's fourth stage is "historical **total and available** funds at every effective/event boundary",
and R-4-050 says affordability is determined by **the combined effect of all proposed revisions**.
R-4-050 governs the historical stage too, so a per-item loop is exactly what it forbids. The item is
not satisfied.

### The scenario that breaks it, which I constructed to be sure this is real

| step | effect |
|---|---|
| fixture | B opening 0, a funder C |
| T1 | A pays B 100 (`p1`) **and** A pays B 100 (`p2`), same instant |
| T2 | B pays C 150 → B = 50 |
| T3 | C pays B 1000 → B = 1050 |
| batch | correct `p1` → 50 **and** `p2` → 50, both effective T1 (each delta −50, debiting B 50) |

- Current-funds stage: `net[B] = −100` against available 1050 → passes, correctly.
- Historical **per item**: `p1`→50 alone gives B 150 at T1 and 0 at T2 → clean. `p2`→50 alone, likewise
  clean. So the existing loop returns `201`.
- Historical **combined**: B is 100 at T1 and **−50 at T2** → `409 historical_overdraft` is required.

A negative balance at a past boundary, accepted. That is the invariant class this whole track exists to
protect, so it is worth the clock even this late.

### The process point, logged against @builder

The disclosure was honest and accurate — and addressed to a future code reader instead of to me. Had I
closed N4-5 on the test counts, I would have closed a requirement the implementation states in writing
it does not meet. Lesson recorded: **a comment is not a disclosure**; an unbuilt requirement goes in the
handoff message with its id, and "no test exercises it" is a reason to flag it harder, not softer —
in a stage with hidden checks, a missing visible test is the strongest hint that an unseen check exists.

N4-5 re-dispatched with the scenario above. Governor `--node N4-5`: `g8: PASS — within caps`.

---

## TICK 2026-10-06T01:30Z — BREACH confirmed independently, fixed, and verified. One half remains.

### @adversary found the same gap, with a better demonstration

While I was constructing my counterexample, @adversary built one and **executed** it: A opening 150,
A→B 100 at T1, A→C 40 at T2, D pays A 200 so current total survives the batch; then a batch raising both
to 110 and 50. Each item alone lands exactly on `0` at T2 when checked against the sibling's unchanged
amount; together, T2 is `150 − 110 − 50 = −10`. The batch returned `201` and then
**`GET /me?as_of=<T2>` returned `{"total": -10}`** — a plain read serving a negative balance.

That is strictly stronger than my version, which showed only the missing rejection. @adversary showed
the *observable consequence*: R-3-002 violated on an ordinary read, which is the single worst outcome
this track defines. Two independent constructions of one gap, and it is now a permanent test —
`test_n4_3_adversarial.py::test_batch_historical_overdraft_check_misses_cross_item_combination_r_3_002`.
Adversarial tests are inside gate 2's collection (167 of the 679 collected), so no seat can accept work
over it.

### @builder's fix at `05565a3` is correct, and I verified the mechanism

New `would_candidates_cause_historical_overdraft(…, candidates: dict, affected_user_ids)` in
`revisions.py:199`: it replays each affected user's history with **every** candidate applied together,
falling back to each other payment's current latest revision, and **batches simultaneous movements at
one instant before testing nonnegativity** — which is R-3's "balances at a boundary include the combined
effect of all movements at that instant", a detail neither counterexample forced it to get right.

The signature is the point. I had told @builder that a function taking one candidate cannot answer a
combined question and to ask rather than guess the shape; it built the plural form directly. That covers
both shapes — @adversary's two increases from one payer at different instants, and my two same-instant
decreases against one receiver.

### The remaining half: `available`, not just `total`

The combined walk tracks **total only**. `grep -c held stage-4/service/revisions.py` → **0**. But
R-4-049's fourth stage is "historical **total and available** funds at every effective/event boundary",
and R-3-118 says the same for single corrections. So the available half is unimplemented in the
historical direction — and this is pre-existing, not introduced by N4-3.1: the single-correction path
has never checked it either, which is a defect in stage 3's closed content.

Reachable, and the current-funds stage does **not** catch it, because a released hold leaves present
available healthy while a past window was not:

| step | effect |
|---|---|
| B opening 0 | — |
| T1 | A pays B 100 → total 100 |
| T2 | B opens a hold of 90 → available 10 |
| T3 | B voids the hold → available 100 |
| T4 | C pays B 1000 → total 1100, available 1100 |
| batch | correct the T1 payment to 50, effective T1 (debits B 50) |

Current stage: `net[B] = −50` against available 1050 → passes. Historical **total**: 50 at T1, 1050 at
T4 — never negative. Historical **available**: between T2 and T3, `50 − 90 = −40` → `historical_overdraft`
is required and is not raised.

`holds.py` already has the tooling — `held_at(store, user_id, as_of_epoch, known_at_epoch)` at `:98` and
`remaining_at` at `:54` — so this is a matter of subtracting `held_at` at each boundary inside the walk,
not new machinery.

**Ranked honestly:** below confirming the landed fix. It needs a hold in the corrected history to bite,
the stage-3 single-correction path shares the gap, and the clock is late. Dispatched as the remainder of
N4-5; if the clock ends first it is recorded as a known gap with this scenario, not chased.

### @redline's duplicate test request is withdrawn

I asked @redline for a combined-historical-overdraft test. @adversary's permanent test already covers it
and sits in gate 2's collection, so the duplicate buys nothing. Withdrawn before it was started.

---

## TICK 2026-10-06T01:50Z — N4-7 and N4-C5 cancelled: I invented them. N4-8 is already satisfied. The endgame is one gap and the close.

### Two items in my own plan are not requirements

I checked the specs instead of my plan:

| file | `data-testid` | `browser` / `screen` / `route` |
|---|---|---|
| `stage-2.md` | 7 | present |
| `stage-3.md` | **0** | **0** |
| `stage-4.md` | **0** | **0** |

**Every UI requirement in the pocketful track comes from `stage-2.md`** and is carried forward intact —
which is exactly what gate 7 checks, and g7 has been PASS throughout stage 4. So:

- **N4-7 ("UI for refunds and batch corrections") is cancelled.** Not deferred, not partial —
  it was never a requirement. I wrote it into `plan/s4-dag.md` myself.
- **N4-C5 ("statement and correction UI", re-homed from N3-10) is cancelled** for the same reason:
  `stage-3.md` specifies no UI either.

This matters for the final report, which would otherwise have claimed stage 3 and stage 4 shipped with
UI work undone. The honest statement is the opposite: **stages 3 and 4 add no UI surface, and the
stage-2 UI they carry is intact and verified by g7.** Reporting invented scope as a shortfall would have
understated the result and misled anyone reading it.

It also would have cost the last of the clock. Had I dispatched N4-7 instead of checking, @builder would
have spent the remaining stage budget building screens no check asks for, while the one demonstrated
money gap went unfixed.

### N4-8 is already satisfied

At N4-3's gate-2 run (`N4-3-g2-20261005T184705-a864.log`): **678 passed, 1 failed**, and that single
failure was @adversary's own BREACH test. So all three of `test_concurrency_s4.py`'s tests — R-4-081
(concurrent refunds beyond the cumulative ceiling), R-4-082 (refund racing a correction), R-4-083 /
R-4-059 (concurrent batches sharing a payment) — were **already green**. The existing global write-lock
discipline satisfies them; no N4-8 build item is needed, and g4's 1300-op storm passing repeatedly is
independent corroboration.

As with N4-5's first three stages, the work was done inside an earlier item rather than left undone. I am
recording it as satisfied-by-evidence, not assuming it.

### What is actually left

1. **N4-5's `available`-at-historical-boundaries half** — the one demonstrated, reachable gap
   (released-hold scenario, two ticks up). @builder has it.
2. **The stage close** — `--gates all --track pocketful --kickoff /home/prashant/projects/dark-factory-wearedevs`,
   with `--scope cc9544e..<tip>`.

That is the whole remaining stage. Everything else has either landed or turned out not to be a
requirement.

---

## TICK 2026-10-06T02:10Z — @verifier's g5 FAIL is explained: it gated pre-fix code. BUILD PHASE COMPLETE. Stage close dispatched.

### The g5 mystery dissolves — no debug hunt needed

@verifier reported g5 failing at `640dd90` with the snapshot-token 404, read the whole export/import
path, found "every piece structurally correct in isolation", could not reproduce it live, and asked for
@builder's eyes with a debug repro. **That would have spent the stage's last clock chasing a bug that no
longer exists.**

The gate result and the code reading came from two different trees. Proof:

```
git merge-base --is-ancestor 40cc5c0 640dd90   ->  false   (fix NOT in the gated commit)
git show 640dd90:stage-4/service/snapshot.py | grep -c statement_snapshots  ->  0
git show 40cc5c0:stage-4/service/snapshot.py | grep -c statement_snapshots  ->  8
```

`640dd90` predates N4-6's fix. The gate ran code in which `statement_snapshots` is **absent from the
export module entirely**, while @verifier's static reading was of the working tree, which contains the
fix — which is precisely why every piece looked right. A green-looking code read against a red gate is
the signature of reading the wrong tree. Lesson recorded against @verifier: read the code **at the
commit the gate ran** (`git show <gated-sha>:<path>`), and confirm containment with
`git merge-base --is-ancestor`.

Worth saying the rest plainly: that run was otherwise excellent — scope PASS at the corrected base, g1,
g4 (1300 ops), g8 PASS, g2 677/1, and all three frozen earlier-stage suites clean at 314/314, 497/497,
616/616. It also correctly declined a GO rather than waving the failure through.

### The build phase of stage 4 is complete

| item | state | commit |
|---|---|---|
| N4-1 refunds | closed | `c18a18e` |
| N4-2 floor + two-sided available debit | done | `ab99464`, `14f5fc0` |
| N4-3 correction-batches validation | done | `571aec7` |
| N4-3.1 cross-item historical (BREACH fix) | done | `05565a3` |
| N4-4 batch commit semantics | done | `f16dd5e` |
| N4-5 historical walk covers **available** | done | `b6715d7` |
| N4-6 snapshots survive import | done | `40cc5c0` |
| N4-H hook verification | closed, no change needed | — |
| N4-H2 / N4-H3 part 1 UI condition waits | done | `1af8134`, `47a03e8` |
| N4-8 concurrency | **satisfied by evidence** (678/1 at N4-3's run; the 1 was the BREACH test) | — |
| N4-7, N4-C5 | **cancelled — never requirements** | — |

Ten requirements-bearing items, two cancelled as invented, one satisfied without an item.

### The close is pinned to a commit, deliberately

Dispatched with **`--commit <tip>`** so the run gates a fixed sha in its own worktree. That isolates it
from @redline's in-flight N4-H3 part 2 (the computed-value sweep), which may still touch test files:
without the pin, a test edit landing mid-run would change the suite underneath a 30-minute g6. @redline
therefore continues in parallel rather than blocking the close — and if part 2 lands before the run
starts, so much the better for g6.

---

## TICK 2026-10-06T02:25Z — first fully green suite (679/0). One landed money change is still unattacked.

### N4-4 HOLDS, and the suite went green

@adversary's run at `d89b36b`: **g2 PASS 679/0** — the first fully green stage-4 gate 2 of the run,
including its own BREACH test and the `test_settlement_membership_corrections_and_snapshots_survive_import`
that had been the 677/1 failure. g4 PASS (1300 ops), g8 PASS. That independently confirms two fixes at
once: N4-3.1's cross-item historical check and N4-6's snapshot survival.

Six probes on N4-4, all passing, and two are ones I would not have thought to specify:

- **R-4-053 via the max, not the clock:** a single correction to P1, then immediately a batch touching
  both P1 and an untouched P2. The batch's shared `recorded_at` is strictly later than P1's own prior
  timestamp, and both new revisions carry it identically — proving the implementation takes the max
  across every touched payment rather than trusting `now()`. That was trap 1 in the N4-4 dispatch and it
  is now positively confirmed rather than merely not-failing.
- **R-4-056 retry identity across a correction:** a payment's own creation-idempotency replay, requested
  *after* a batch corrected that payment, still returns the **original** creation body. That is the
  "original receipts never change" requirement tested from the direction that would actually break.

**@adversary caught its own test-construction bug mid-pass again** — computing `effective_at` with
`datetime.now()` inside each racing thread, so the "identical body" replay race was not actually
identical. Second self-catch in two items, and both times before trusting the result.

### The gap: `b6715d7` has never been attacked

```
git merge-base --is-ancestor b6715d7 d89b36b  ->  false
```

N4-5's available-at-boundaries fix is **newer** than every attack pass and every green gate run. It is
the stage's last change, it is a money path, and it is the only landed commit no seat has probed. The
close run gates it, but a close gate is a suite, not an attack — and the two gaps found in this stage's
money paths were both found by attack, not by the suite.

Dispatched as **N4-5.1** to @adversary. Governor: `g8: PASS — within caps`. The two things worth
attacking hardest are the ones I flagged to @builder and then had to partially retract: the
released-hold scenario (`available` negative in a window that present funds no longer reveal) and the
`held_at` axis question — I ruled the one-axis call correct for affordability, and if that ruling is
wrong, this is where it shows.

### N4-5 verified at the call sites, plus one fragility recorded rather than actioned

@builder's report crossed my verification. I checked the thing its summary made me want to check: it
threaded `store` through as an **optional** parameter, and the available half is guarded by
`if store is not None`. An optional argument whose absence silently disables a money check is the exact
shape of @redline's own lesson about checks guarded by the truthiness of the thing they verify — and the
docstring documents the skip as a feature: *"omit it to check `total` only."*

So I enumerated every call site rather than trusting "both call sites now pass it":

```
corrections.py:151          … (payer_id, payee_id), store=STORE)      ✓
correction_batches.py:236   … affected_user_ids, store=STORE)         ✓
revisions.py:287            wrapper forwards store=store             ✓
```

Two call sites, both pass it, and the single-correction wrapper forwards it. **No defect today** — the
available check is live on both paths, which is what the requirement needs.

**Recorded as a fragility, not dispatched as work.** Making the parameter required would be a one-line,
behaviour-preserving change that converts a silent weakening into an immediate `TypeError`, and a
stage-5 copy-forward or any new call site that forgets `store=` would otherwise get a quietly weaker
money check with no signal. But the close run is in flight, and changing a money path to improve a
property that is currently satisfied is not a trade I will make at this point in the stage. It goes in
the final report as a known fragility with the one-line fix named.

---

## TICK 2026-10-06T02:45Z — N4-H3 closed in detail; close sequencing handed to @verifier; scratch cleanup queued as the last step

### N4-H3's part 1 was a harder problem than I framed it as

I told @redline to apply "the same condition-wait pattern" to 11 sleeps. It found that the 11 needed
**four different signals**, not one, and built shared helpers rather than forcing the balance-change
pattern everywhere:

- `wait_for_response_to` where the dependency is just "the request resolved" — and it checked
  empirically, via `page.on("request")`, that resubmitting an unchanged form actually fires a network
  request **before** relying on `expect_response`, which would otherwise hang forever.
- `wait_for_present` / `wait_for_absent` where the assertion is itself about DOM presence — including
  the `route.abort()` cases, where `expect_response` *would* hang by construction, and the idempotent
  replay that has no balance change to key off.
- `wait_for_dom_change` generalised to diff an attribute as well as text.

My instruction would have produced a hang in at least two of the 11. 46 UI tests green across three
consecutive runs; the 6 correctly-triaged non-defect waits untouched.

### Part 2 found 20 status-code-only money assertions

Across 6 of the 7 new files — the exact gap stage 3's surviving `revisions.py:158` sign-flip exploited.
Two judgements worth recording:

- For `test_batch_replay_returns_original_response` and the two concurrency tests, response-body
  equality and a bare status code **cannot** catch a double-apply or a wrong-amount win. It added
  balance checks that read back actual server state, and for the concurrency cases read back
  *whichever side won* via `GET …/revisions` rather than assuming a winner.
- It left pure permission/validation tests alone (401/403/404/422 before anything moves) — no
  arithmetic there for a mutation to corrupt. That restraint is as useful as the additions.

61/61 across the 7 files, twice. Suite now **680**.

### The close: sequencing is @verifier's call now

@verifier judged it better to hold the close until N4-5.1 clears, against my "run it now". **It is
right and I withdrew my instruction.** A full `--gates all` close with a 30-minute g6 is the most
expensive run in the factory, and `b6715d7` is the stage's last money change with no attack pass on it.
This is my own rule — sequence the costliest step after the decision has survived one further check —
which I failed to apply to my own dispatch. Bound given: run it anyway if the governor tightens or
N4-5.1 goes quiet, disclosing that `b6715d7` went ungated by attack. That call does not come back to me.

### Scratch: no deliverable risk, but 34 files to clear as the final step

@redline hit a collision on `stage-4/_restart_server.py` — two seats using one scratch path with one
hard-coded port, overwriting each other's pidfile mid-session. Recorded as a lesson: scratch must be
seat-namespaced (`_<seat>_<purpose>.py`) with a per-seat base port, stated in a stage's first dispatch
rather than after a collision.

**Checked whether this can reach the delivered artifact: it cannot.** `stage-4/Dockerfile` copies
explicitly — `COPY main.py ./main.py` and `COPY service ./service` — not `COPY . .`, so root scratch is
outside the image regardless. There is no `.dockerignore` and none is needed.

But **34 untracked files** now sit at `stage-4/`'s root. The close run is pinned to a commit and runs in
a private worktree, so untracked files cannot affect it — which is why cleanup is sequenced **after**
the close, not before: clearing 34 files while the most expensive run in the stage is in flight buys
nothing and risks exactly the kind of mid-run disturbance the pin exists to prevent. Each owning seat
clears its own with `git clean -f -- <explicit paths>`, and **nothing under `stage-*/tests/`**.

---

## >>> STAGE 4 RECORDED `partial`. 2026-10-06. Ledger `6c95e66e1c89` at `fcb9d02`. <<<

g6 **completed** — it never hung, and I was twice wrong about its state:

```
RESULT: FAIL — killed 7/10 valid mutants (70%, need 80%); 0 stillborn; 0 timed out; 455 candidates;
  survivors: #5 service/revisions.py:308 [cmp < to <=]
             #7 service/snapshot.py:374 [or to and]
             #9 service/routes/refunds.py:37 [true to false]
```

**Per the rule I pre-committed before the run, this is the draw: accept it, no re-run, record partial
with g6 named. Nothing returns to a seat.** That pre-commitment is the only reason this decision is
clean — had I set the rule after seeing 70%, deciding not to re-roll would have been indistinguishable
from deciding to re-roll, and stage 3 showed what chasing a resampled score costs.

It also matters that g6 reported `0 timed out` and `455 candidates`: the gate worked correctly and the
score is a real measurement, so the report says **partial with g6 at 70%**, not the weaker
"partial with g6 unmeasured" I had prepared for.

### The final close record

| gate | result |
|---|---|
| scope | PASS `cc9544eb75..5c99bb4` |
| g1 | PASS — built and healthy offline |
| g2 | PASS — 681 passed, 0 failed, 0 errors, 0 skipped |
| **g3** | **PASS — claimed stage 4; suites `{1: pass, 2: pass, 3: pass, 4: pass}`** |
| g4 | PASS — invariant held over 1300 ops |
| g7 | PASS — 6 routes clean at 375/768/1280 |
| g8 | PASS |
| g5 | FAIL → ruled test-side, hook fixed at `1417531`, re-run dispatched for the record |
| **g6** | **FAIL — 70% (7/10), three survivors above** |

Service content is byte-identical from `5c99bb4` through `fcb9d02`
(`git diff --name-only 5c99bb4..fcb9d02 -- stage-4/service stage-4/main.py stage-4/Dockerfile` → empty),
so every behaviour gate above describes the recorded tree.

### Two things I got wrong about g6, both recorded

1. I read "no RESULT" plus a `.junit.xml` as completion and told @verifier to **abandon and restart** it.
   It was alive at mutant 6 with four verdicts banked; a restart would have discarded them. Corrected
   before @verifier acted.
2. I then read three consecutive checks stalled at mutant 7 as possible death, and **held anyway** on
   the grounds that the gate's own timeout is the arbiter rather than my impatience. That was right: it
   finished with a real score. The lesson is the same in both directions — read the artefact's contents,
   not its existence, and let a tool's own timeout decide a tool's own liveness.

### N4-A1 closed clean — `fcb9d02`

@adversary found a legitimate no-docker route (`g2_spec_tests --base-url`, verified from
`factory/gates/common.py` that it skips `service.build()` entirely), fixed the demonstrated flake with a
condition wait on the observable outcome while **leaving R-2-154's engineered delay intact**, and
triaged the other 8. Its conclusion differs from @redline's for `test_ui_*.py` — it found **no**
deliberate-timing cases among its 8, because each was a settle-wait after an already-ordered action
rather than a race construction, and it reasoned each one individually. Different files, different
answer, both defensible. Validated 5/5 identical passes. Verified by me: scope touches only its two
files, **no deletions**, count holds at **681**.

### Next: the operator's browser-product item is now unblocked

The close is recorded, so U1 dispatches. The "before" gate-7 baseline is this run's output.

### R-U-050 "before" baseline — recorded, verified present

The operator requires before/after gate-7 screenshots in this file. The **before** set is the stage-4
close run's g7 output, from `evidence/gates/s4/close-g7-20261005T192753-0d39.log`
(`RESULT: PASS — 6 route(s) clean at 375/768/1280`):

```
evidence/ui/s4/            18 files, 728K — 6 routes × 3 viewports
  home-375.png            home-768.png            home-1280.png
  login-375.png           login-768.png           login-1280.png
  signup-375.png          signup-768.png          signup-1280.png
  requests-375.png        requests-768.png        requests-1280.png
  authorizations-375.png  authorizations-768.png  authorizations-1280.png
  split-375.png           split-768.png           split-1280.png
```

Counted and confirmed on disk, not taken on report. **This set must not be overwritten**: U1/U2/U3's
gate-7 runs write to the same `evidence/ui/s4/` path, so the "after" comparison depends on these files
being preserved. Copied nothing yet — flagging it here because the first `--gates all` after U1 will
otherwise silently replace the baseline the operator asked for.

### The g5 record-run is no longer needed as a separate run

I had asked @verifier for `--gates 5 --commit fcb9d02` to establish whether @redline's hook fix clears
g5. That is now redundant: **U1's `--gates all` (R-U-052) includes g5**, at a commit containing
`1417531`, so the measurement arrives for free with work that has to happen anyway. One fewer image
build on a host that has already been contended for.

---

## TICK 2026-10-06T03:10Z — second BREACH fixed; the close is unblocked and runs in parallel with the attack

### The BREACH: a malformed imported snapshot 500'd a plain read

@adversary at `0d4c04d` — `GET /statement?snapshot=<crafted>` returned a bare **500**, an R-1-005
violation reachable through the unauthenticated import endpoint. Cause: `snapshot.py` validated that
`statement_snapshots` was an object and that each entry's `user_id` was known, and nothing else, while
`statement.py` dereferenced `frozen["entries"]`, `frozen["opening_balance"]` and
`frozen["closing_balance"]` with no fallback.

**This was my miss as much as a defect.** Both @verifier and I had read that validation — it appeared in
@verifier's own trace as "parses it back with the same key and user_id check" — and neither of us asked
whether it was *complete*. Seeing a validator and checking a validator are different acts.

### Fixed at `9cf1126`, and I verified completeness rather than the test

The test cannot answer the question: it returns early on a `422` import ("already fixed at the import
door — good"), so it passes whether or not the read path was hardened. So I checked the only thing that
settles it — **does the validator cover every field the read path dereferences without a fallback?**

| field | read path | validated at import |
|---|---|---|
| `entries` | `frozen["entries"]` (bare) | list of dicts ✓ |
| `opening_balance` | bare | int, bool excluded ✓ |
| `closing_balance` | bare | int, bool excluded ✓ |
| `known_at_raw` | `frozen.get(...)` — **safe** | not needed ✓ |

Complete; the live 500 is closed. @builder also widened the door usefully on its own initiative
(R-1-204a: import now enforces the same stated invariants reset does, so a negative balance cannot be
illegal through one door and legal through the other).

**~~Recorded as a fragility, not chased~~ — RESOLVED at `64919dc`, correcting this record.** I wrote
that the three accesses were still bare and that the guarantee rested on the validator staying in sync
with the read path, and queued it for the final report as an unfixed fragility. @builder then landed
**N4-6.1 part 2**, the second half I had originally asked for, and it is placed better than I specified:

```python
if candidate is None or candidate.get("user_id") != ctx.user["id"]:
    raise not_found("no such snapshot")
# R-1-005: defensive, in addition to import-side validation — a stored
# snapshot this read path cannot safely serve (… from a future field this
# check wasn't updated for …) must never crash a plain read
if (not isinstance(candidate.get("entries"), list) or …):
```

The guard sits at the **lookup**, so a malformed stored snapshot is unresolvable exactly as an unknown
token is (`404`, R-3-084), rather than patching each dereference site. It also closed one more bare
access (`candidate["user_id"]` → `.get("user_id")`). The comment names the future-field scenario I had
flagged as the residual risk, which means the fragility is addressed at its cause and not just at the
one shape @adversary found.

**So this does NOT go in the final report as a known gap.** The `store=None` fragility is separate and
still stands.

### The N4-6 surface is now provably complete, and I checked the claim rather than relaying it

@builder reported that `statement.py`'s frozen dict is exactly
`{user_id, known_at_raw, entries, opening_balance, closing_balance}` — no stored `from`/`to`,
default-`to`, or selected-revision fields, because the window is baked into `entries` and the two
balances at freeze time and never re-derived from stored bounds. That claim decides whether the two
guards are complete or merely cover the one shape @adversary happened to find, so I verified it:

```
statement.py:188-189   frozen = {"user_id": …, "known_at_raw": …, **self._compute_window(ctx, fields)}
_compute_window        BOTH return paths → {"entries", "opening_balance", "closing_balance"}
```

Five keys, confirmed at both return sites. So the import validator (`9cf1126`) and the lookup guard
(`64919dc`) between them cover **every** field, and `user_id`/`known_at_raw` are `.get()`-accessed.
There is nothing further to validate on either side of this endpoint.

**Consequence for @adversary's N4-6.2 brief:** the sub-target I gave it — "fields the read path may touch
only on a *later* page rather than the first" — is **moot**; no such stored fields exist. Its other
sub-targets (internally inconsistent but well-typed `entries`, a token owned by a known user who is not
the caller, and the same crafted shapes through `reset` now that R-1-204a claims both doors enforce the
same invariants) remain live. Not interrupting its in-flight pass to say so — it will reach the same
conclusion from one grep, and a mid-attack turn costs more than the duplication saves.

### Reversing my own hold: the close runs now, with the attack in parallel

I told @verifier twice to hold the close for an attack pass. **Changing that, for a reason that has
changed rather than because I am impatient:**

1. `b6715d7` still has no *completed* attack pass — @adversary went to attack it and found the N4-6
   breach instead, which is better work but leaves that commit unprobed.
2. The close has been deferred through **two** BREACH rounds. A third deferral stops buying
   proportionate assurance.
3. **The constraint I had wrong: an attack does not need the docker lock.** @adversary works against a
   served instance, not a container gate, so attack and close are not mutually exclusive. I had been
   serialising two things that can run at once.

So @verifier closes at `9cf1126` or later, pinned, while @adversary attacks the same tree in parallel.
If @adversary breaks something we fix and re-close if the clock allows; if not, the close stands and the
parallelism cost nothing. The pin is what makes it safe — a pinned run cannot be disturbed by anything
either seat does afterwards.
