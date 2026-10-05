# Redline: a tests-first dark factory (pocketful)

Most bands in this hackathon prove their work with the public checks, which cover 79% of pocketful's stage 1 and only 9% of stage 3. Redline writes its own tests from the spec before any code exists, attacks every change from a separate adversary seat, and accepts nothing until a seat that did not build it re-runs eight gates on the exact commit.

Team: Prashant Thakur · Track: pocketful · Event: WeAreDevelopers x BAND Dark Factory

## 60-second tour

1. One human message goes into a fresh BAND room, addressed to @Planner. The factory needs nothing else typed after it ([dispatch](dispatch.md)); in the judged run the operator posted four disclosed notes, listed in FACTORY.md, Limits.
2. @Planner turns each stage's spec into numbered requirements (`R-3-041`) and a small work plan.
3. @Redline (Claude Sonnet) writes tests for every requirement before implementation, plus a hook that tells the gates what "money is conserved" means.
4. @Builder (Claude) implements one item at a time against those tests.
5. @Adversary (Claude Sonnet) attacks each item with races, retries, rounding and stale state. Every break becomes a permanent test.
6. @Verifier (Claude Sonnet, read-only) re-runs the gates itself and answers GO, NEEDS_WORK or BLOCK with an evidence block.
7. Gate results, verdicts and costs land in a hash-chained ledger. FACTORY.md's numbers are generated from it.

Start with `evidence/run.html`: a replay of the real room, with every handoff's evidence, every review that changed the work, and the count of human messages after the dispatch.

Results of the judged run: **all four stages pass the kickoff harness** (`harness run --all --mode isolated`, highest contiguous stage 4, `evidence/harness/final/`). The last gate run measured **684 spec tests passed, 0 failed**; at `d6efb05` every one of the eight gates passed, mutation included (90%). The Adversary's attacks produced 18 BREACH verdicts across the run, each fixed and kept as a permanent test, among 91 rejections in all. 512 band commits, each authored by the seat that made it (the `Human` commits are factory and record only, listed in FACTORY.md); 4,746 messages in one BAND room. Spend $1,188 at list price, measured per turn from the seat logs, over 34.8 h. After stage 4, a disclosed operator note asked for a UI pass to the standard of familiar payment apps, and the band built it (design system, dark mode, phone tab bar, statement, payment history, refunds, batch corrections). Stages 2-4 are recorded partial; FACTORY.md, Limits says why. The live build is at https://redline-pocketful.onrender.com and the run's room is in `room.json`; open `evidence/run.html` for a replay. To check any of this in five minutes, see [JUDGES.md](JUDGES.md).

One rule for every number in this repo: it comes from a script reading the ledger, the room or git history, and each figure names its source. Nothing is typed by hand.

## BAND carries the work

Every handoff in Redline is an @mention in the room, because a BAND seat only wakes when addressed. Seats paste the full requirements into each handoff instead of pointing at earlier messages, and every handoff carries a JSON evidence block (requirement ids, commit, the exact command run, pass/fail counts, log path, cost, verdict). The room is the record: `factory/ingest.py` reads `room.json` back into the ledger, and the rejection table in FACTORY.md links each verdict to its room message and to the diff it forced.

```mermaid
flowchart LR
  H[Human: one dispatch] --> P[@Planner<br/>requirements + plan]
  P --> R[@Redline<br/>tests first]
  R --> B[@Builder<br/>one item at a time]
  B --> A[@Adversary<br/>attacks invariants]
  A -- BREACH + test --> B
  A -- HOLDS --> V[@Verifier<br/>runs 8 gates]
  B --> V
  V -- NEEDS_WORK / BLOCK --> B
  V -- GO --> P
  V -.-> L[(hash-chained ledger)]
  L -.-> F[FACTORY.md tables<br/>stage dossier]
```

## The band

| Seat | Runtime | Model | Owns | May edit |
|---|---|---|---|---|
| Planner | Claude Code (BAND SDK) | claude-opus-5 | requirements, plan, stage close | `plan/` |
| Redline | Claude Code (BAND SDK) | claude-sonnet-5 | tests from the spec, before code | `stage-*/tests/` |
| Builder | Claude Code (BAND SDK) | claude-sonnet-5 | service code, Dockerfile, RUN.md | stage folders, not tests |
| Adversary | Claude Code (BAND SDK) | claude-sonnet-5 | attacks; each break becomes a test | `stage-*/tests/adversarial/` |
| Verifier | Claude Code (BAND SDK) | claude-sonnet-5 | the eight gates and the verdict | nothing (gate output only) |

The test writer never sees the code and the verifier can edit nothing; a GO is refused by the ledger unless the gates passed on the exact commit, so passing is a fact, not one model agreeing with itself. (We measured every free non-Claude option and none could sustain a seat; see FACTORY.md.) A scope check reads `git log` and blocks any commit outside its author's edit boundary.

## How Redline maps to the rubric

Factory (50%). The mandates in `mandates/` name no endpoint, field, error code or product noun; `make scan` checks them against both tracks' vocabulary and a noun list, and the same mandates build the toy track as a genericity proof (100% of the toy's stage-1 suite, `proof/toy/`). Effectiveness comes from spec-derived tests aimed at what the public checks leave out, an invariant storm of 1,000+ concurrent operations with replays, and a mutation gate that proves the tests catch bugs. FACTORY.md is a runbook: stand-up in ten minutes, seat rationale, measured cost and time per seat per stage, failed experiments, and the rejection ledger.

App (25%). Gate 7 opens every screen at 375, 768 and 1280 px, fails on horizontal overflow, controls under 24 px, any serious axe violation, assets fetched from outside the container, or missing empty/loading/error states. Screenshots go to `evidence/ui/`.

Agent Teamwork (25%). Five seats: one Opus, four Sonnet with separate contexts and edit boundaries, one dispatch, no human message after it. Each rejection in FACTORY.md shows who raised it, what it caught, the commit range it forced and the room message it came from. The budget governor returns stuck items to @Planner instead of to a person.

## How to read this repo

| Path | What it is |
|---|---|
| `FACTORY.md` | the runbook: stand it up, seats, gates, results, costs, catches, failed experiments, limits |
| `mandates/` | one generic mandate per seat, each starting with `Harness:` and `Model:` |
| `room.json` | the judged run, downloaded from the Band console unchanged |
| `stage-1/` … `stage-4/` | the service, written only by the band, each with `Dockerfile` and `RUN.md` |
| `evidence/run.html` | replay of the room: handoffs, evidence, reviews and the diffs they forced |
| `evidence/` | hash-chained ledger, gate logs, UI screenshots, per-stage dossier |
| `factory/` | the factory: seat runtime, gates 1–8, ledger, governor, report |
| `plan/` | dispatches, decisions, failed experiments, checklists |
| `proof/` | toy genericity run and the plumbing rehearsal |

