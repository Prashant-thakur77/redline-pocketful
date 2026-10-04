# Stage-close procedure — all four stages

## Verification: the planner decides *when*, @verifier resolves *which sha* (revised 2026-10-04)

@builder's handoff does **not** trigger a verification pass. The planner asks @verifier for
a pass when a batch of items is genuinely ready; until then @verifier runs nothing.

**But the planner does not name the sha.** First attempt at this rule had the planner naming
an exact tip, and it failed four times (`13ff358`, `e0e8c45`, `153d782`, then `4f44896`
going stale within minutes of being named): in a tree with five committing seats, any sha a
planner names is obsolete before the receiving seat starts, and twice the named sha did not
even contain the work the dispatch described.

So: **@verifier resolves `git rev-parse HEAD` itself at the moment it begins, runs against
that, and reports which sha it used.** The planner triggers the pass and names the *items*
to disposition; the verifier owns the sha. That eliminates the whole error class rather than
asking the planner to be more careful, which demonstrably did not work.

If a specific historical sha genuinely must be checked, the planner proves the content is in
that commit object first and pastes the output:

```
git cat-file -e <sha>:<path>                      # new file present
git show <sha>:<path> | grep -n '<distinctive line>'   # change present
```

A commit being recent is not evidence it contains anything.

Why: @builder names a per-item sha when it finishes an item, @verifier verifies what was
named, and a fix landing two commits later means the pass judged a superseded commit. That
happened four times in stage 1 — `eacec15`, `12cdcdb`, `223c1b4`, `540803a` — each a
correct finding against a sha that was already obsolete. Nobody was wrong; the sequencing
was, and the sequencing is the planner's. Per-item verification was an artefact of the
per-item `GO` model, which `factory/record.py` cannot support anyway.

Written once, applies to stage 1, 2, 3 and 4. The planner runs steps 1 and 6–8;
@verifier runs steps 2–5 and owns every verdict.

Per-item `GO` is impossible before gate 2 can pass in full — see the second correction in
`plan/s1-dag.md` — so **stage close is where `GO` verdicts are actually issued.** Items
carry `HOLDS` until then.

## 1. Planner: confirm every item is dispositioned

Every item in `plan/s<N>-status.md` is `HOLDS`, `GO`, or `blocked` **with its evidence
and the reason**. No item is left `dispatched` or `built`. A blocked item is named in the
final report with what blocked it; a partial stage that is honest beats a stalled one.

## 2. Verifier: one untagged rehearsal pass

```
.venv/bin/python -m factory.gates.run stage-<N> --commit <tip> --gates 1,2,4,8 \
  --scope <last-GO-or-7fca98b>..<tip>
```

**No `--node`.** `factory/governor.py:41` charges node-tagged rejection events to the
attempts cap, so rehearsal must stay untagged or it eats the budget it is checking.

## 3. Verifier: the full gate run — the authoritative one

```
.venv/bin/python -m factory.gates.run stage-<N> --node close --gates all \
  --scope <last-GO>..<tip> --track pocketful \
  --kickoff /home/prashant/projects/dark-factory-wearedevs
```

All eight gates plus the scope check. This is the only run that carries `--node close`.

## 4. Verifier: read gate 4's status mix, not just its verdict

A green gate 4 proves nothing if the storm's operations never reached the money paths.
At N1-1.2 the log read `statuses {405: 204, 404: 1096}` — conservation over an empty set.

| by the close of | the mix must contain |
|---|---|
| stage 1 | `201` and `409 insufficient_funds` from `/payments`, `POST /requests`, `/requests/{id}/pay`, `/splits`, `/settlements` |
| stage 2 | the above plus `201`/`409` from `/authorizations` and `/authorizations/{id}/capture` |
| stage 3 | the above plus `201`/`409 stale_revision`/`409 historical_overdraft` from corrections |
| stage 4 | the above plus `201`/`422 refund_exceeds_payment` from refunds and `/correction-batches` |

A mix still dominated by `404`/`405` means a verb was never registered and the invariant
is trivially true. This failure mode is silent — none of the eight gates reports it.

## 5. Gate 3 enforces the no-overshoot rule itself

`factory/gates/g3_public_checks.py:35` finishes on
`proc.returncode == 0 and claim == str(gate.stage)`: the harness reports a *claimed stage*
and the gate requires it to equal **exactly** this stage.

So the dispatch's *"stage N must not pass stage N+1's checks"* is a **gate failure, not a
style note**. Building a later stage's feature early fails gate 3 at this stage's close.
Pulling work forward **within** a stage is fine (R-1-163…167 moved from N1-6 into N1-2);
pulling work forward **across** a stage boundary breaks the close. Tell @builder this
before each stage, not after.

## 5a. Verifier: one tagged pass per item, to make the record honest

Two defects in how I set this up, found by reading `factory/metrics.py` and
`factory/report.py`:

**Rejections are only marked recovered by a later `GO`.** `metrics.py:63-65` resolves
`recovered_by` as the next verdict on the same node whose verdict is `GO`. Under the
HOLDS model nothing ever gets one, so `factory.report` would present all 11 stage-1
rejections — including three genuine breaches that were fixed — as never recovered. That
would misrepresent the run.

**Fix, and it is free:** once the stage-close run has gate 2 green, run **one tagged pass
per item at the final commit** and record `GO` for each node that passes. `is_go()` needs
gate results for that exact node at that commit, which is why the close-tagged run alone
is not enough. It costs no budget: `governor.py:41` counts only *rejection* verdicts, and
these runs pass.

```
for n in N1-1 N1-2 … ; do
  .venv/bin/python -m factory.gates.run stage-<N> --commit <final> --node $n --gates 1,2,4,8
  .venv/bin/python -m factory.record verdict --stage <N> --node $n --verdict GO --commit <final> --text "…"
done
```

**One item cannot be made whole this way: N1-1.** Its attempts are permanently 6 > cap 4,
so gate 8 fails for that node forever and `is_go()` will always refuse. Its rejections
therefore stay `recovered: no` in the generated report even though they were fixed
(`fce263e` for R-1-079, `13ff358` for R-1-080a). **The final report must say so explicitly
and name those commits**, rather than let the generated table imply the breaches are open.

## 5b. Every seat: record cost events, or the report has no cost

`evidence/ledger.jsonl` currently holds 13 handoffs, 156 gate results, 17 verdicts and
**zero `cost` events**, so `factory.report --summary` prints `spend $0.00` and
`cost_rows()` is empty. Seats have been putting cost in their message EVIDENCE blocks,
which the ledger never sees — my omission: I asked for the block and never asked for the
event.

Each seat records its own, per item or per stage:

```
.venv/bin/python -m factory.record cost --stage <N> [--node <id>] \
  --seat <planner|redline|builder|adversary|verifier> \
  --tokens <T> --usd <U> --seconds <S>
```

No seat records another's figures. They are best estimates from the seat's own evidence
blocks, and the final report must label them as estimates.

## 6. Planner: record the close

```
.venv/bin/python -m factory.record stage_closed --stage <N> --result closed|partial|blocked
```

`closed` only on a gate-3-claiming, all-gates-green run. `partial` when some items are
blocked but the stage otherwise holds — and say which in the final report.

## 7. Builder: copy forward

```
.venv/bin/python -m factory.stage_copy stage-<N> stage-<N+1>
```

Refuses to overwrite and never carries a nested `.git`, build output or caches. Never put
next-stage work into an earlier folder.

## 8. Planner: open the next stage

Dispatch `N<N+1>-T` to @redline with the next stage's requirements pasted in full
(`plan/s<N+1>-requirements.md` is already written for all four stages), then the build
items in dependency order. Remind @redline that `stage-<N+1>/tests/` arrives as a copy of
the previous stage's suite: the earlier tests must keep passing (gate 5) and the test
count ratchets upward across this and every earlier stage (gate 2).

## Carried-forward hazards, every stage

- **R-1-112** — a replay returns the **stored** response body verbatim, never re-rendered.
  A later stage adding a field to the payment object (stage 2 `authorization_id`, stage 4
  `refund_of`) must not change replays of keys claimed earlier. Breaks as a **gate 5
  upgrade failure**, one stage after the mistake.
- **R-1-086a** — login does equal work for an unknown email and a wrong password.
- **R-1-051** — a seeded `paid` request exposes `payment_id: null`; never synthesize.
- **R-1-080a** — client-caused errors are 4xx; a genuine uncaught exception is `500
  internal_error` and loud. Never relabel an internal defect as a client error.
- **Gate 5's `carry`** uses @redline's hook `snapshot()`, a semantic fingerprint — balances,
  pre-upgrade token validity, request states, settlement membership, the same-key retry
  body. It must stay free of version-specific fields as stages add them.
