# Final report — DRAFT, pending stage 4's close

Not yet posted. Stage 4's close run is in flight; every figure below that is not marked
`[PENDING]` is final. All monetary and gate figures come from
`python -m factory.report --summary --repo <repo> --ledger <repo>/evidence/ledger.jsonl`,
never hand-computed. (Note: the tool needs those flags explicitly unless run from the repo
root — run from elsewhere it silently reports only the current stage.)

Ledger hash chain: `python -m factory.ledger evidence/ledger.jsonl` → **ok** (2,268 events).

## Per-stage results

| stage | result | gates | rejections | spend |
|---|---|---|---|---|
| 1 | **closed** | g1–g6, g8 PASS; **scope FAIL** | 32 | $282.75 |
| 2 | **partial** | g1–g5, g7 PASS; **g6 FAIL, g8 FAIL**, scope FAIL | 17 | $309.84 |
| 3 | **partial** | g1–g5, g7, g8, scope PASS; **g6 FAIL (70%)** | 11 | $84.13 |
| 4 | `[PENDING close]` | g1, g2, g4, g8, scope PASS; g5 stale-FAIL (pre-fix) | 1 | $0.00 recorded |

Total recorded spend: **$676.72**. By seat: planner $236.17, builder $212.02, verifier $118.83,
redline $110.99, adversary $90.51 (seat figures are list-price estimates from seat evidence blocks,
per FACTORY.md's stated limitation).

Verdict counts across the run: HOLDS 94, NEEDS_WORK 46, READY 15, BREACH 12, GO 10, BLOCK 3.

## Why stages 2 and 3 are partial

**Both on gate 6 (mutation), not on product behaviour.** Gate 6 samples 12 mutants per run, so its
score is a draw rather than a measurement. Stage 3 scored 70% (7/10 valid) on a single draw with three
survivors:

- `idempotency.py:140` — `with self._lock:` → `if True:`
- `revisions.py:158` — `total += -rev["amount"] if is_from else rev["amount"]`, sign flipped
- `idempotency.py:159` — `if entry.state != "complete":` → `== "complete"`

Two of the three only change behaviour under a specific interleaving, and gate 6 does not run the
storm, so no test it executes can observe them — close to unkillable by construction under a
12-mutant sample with no concurrency harness. The third is a genuine test-strength gap.

Stage 2 additionally failed g8 (budget) — its own clock and spend caps.

**Every gate that measures money was green in both stages**: g4's 1,000+ op storm with 30% replays,
g2's full suite, g5's earlier-stage regression. No conservation, nonnegativity or at-most-once
violation survived into any closed stage.

## Scope failures, and one is mine

Stage 1's and stage 2's scope FAIL are recorded violations, and the stage-1 one is a process failure
of **mine**: commit `db83d89` has the planner authoring @builder's stage-1 service content
(Dockerfile and sources), outside the planner's `plan/` boundary. @verifier issued a BLOCK, I
accepted it as a standing violation rather than rewriting history, and it kept that gate red. Stage 2
carries copy-forward artifacts of the same class.

Stage 3 and stage 4 both have **scope PASS**, after @verifier diagnosed the structural cause: a
`stage_copy` makes @builder the author of everything under the new folder's `tests/`, so the scope
base must be the copy-forward commit itself (`7d8405b` for stage 3, `cc9544e` for stage 4), not the
previous stage's base.

## Defects found and fixed, by who found them

| defect | found by | mechanism |
|---|---|---|
| Correction-batch historical check missed cross-item combinations → `GET /me?as_of=` served `total: -10` | @adversary (BREACH), independently constructed by @planner | per-item replay against siblings' stale amounts |
| Statement snapshot tokens did not survive export/import (R-4-070) | @redline's hook verification, and @verifier's g5 | `statement_snapshots` absent from `snapshot.py` entirely |
| Historical overdraft checked `total` but never `available` (R-3-118) | @planner, from @builder's own disclosure | `grep -c held revisions.py` → 0 |
| `insufficient_funds` computed from an opening balance, and decreases never funds-checked | @planner | `corrections.py` ceiling used opening balance; `if delta > 0` skipped the receiver |
| Captures/refunds correctable; refund floor absent | @builder, @redline tests | — |

**Stage 3 shipped a defect stage 4 found and fixed**: the `insufficient_funds` / `historical_overdraft`
split. It falsely rejected affordable increases and never funds-checked decreases. A wrong-code and
false-rejection defect, not a conservation one — no money could be created or destroyed by it. Stage 3
was already recorded partial and is not reopenable, so the fix lives in `stage-4/` plus a back-ported
test in `stage-3/tests/`.

## Two items in my own plan were never requirements

`stage-3.md` and `stage-4.md` contain **zero** occurrences of `data-testid`, `browser`, `screen` or
`route`; all UI requirements come from `stage-2.md` (7 `data-testid` mentions) and are carried forward
intact, which gate 7 verifies and which passed throughout. **N4-7 ("UI for refunds and batch
corrections") and N4-C5 ("statement and correction UI") were scope I invented** and are cancelled, not
deferred. Reporting them as shortfalls would have understated the result; building them would have
spent the last of the stage budget on surface no check asks for.

## Known gaps, stated plainly

1. **`store` is an optional parameter on the historical-overdraft primitives**, and its absence
   silently disables the `available` half of the check. Both current call sites pass it
   (`corrections.py:151`, `correction_batches.py:236`, wrapper forwards), so there is **no defect
   today** — but a new call site or a stage-5 copy-forward that forgets `store=` would get a quietly
   weaker money check with no signal. One-line fix: make the parameter required. Not applied because
   the close run was in flight and the property is currently satisfied.
2. **Gate 6 remains a 12-mutant spot check**, not mutation testing.
3. `factory.report` prints `stage 4: blocked` from a stale gate-8 artefact created when stage 4 was
   opened prematurely at 12:30 and withdrawn; the live record is `plan/s4-status.md`.

## What the record shows about the method

The two most expensive defects in stage 4 were both found by **attack or by independent verification,
not by the test suite** — the suite was fully green (679/0) while the cross-item historical gap was
live. Three times a seat caught an error by reading the primary artefact instead of trusting a
summary: @redline on two mutant branches I had paraphrased wrongly, @builder twice on tests that
asserted the opposite of their cited requirement. Twice @adversary caught a defect in its own
instrument before blaming its subject. And once @verifier's own escalation was wrong in a way worth
recording: it read code in the working tree to explain a gate failure from an earlier commit, which
would have sent @builder debugging a bug that no longer existed.

`plan/lessons.md` carries the generic root cause of each, including five entries against the planner.
