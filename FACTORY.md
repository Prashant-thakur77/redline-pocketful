# Redline factory

Tests are written from the spec before the code, and nothing ships until a seat that did not build it proves it with evidence it produced itself.

| Case study | |
|---|---|
| Task | pocketful, a Venmo-style wallet in four stages; money must never be created, destroyed or spent twice |
| Band | five BAND SDK seats on Claude Code: Opus (plan, tests, verdicts), Sonnet (build, attacks); each with its own context and edit boundary |
| Key design decision | the test writer never sees the code and the verifier never edits it; eight gates are scripts, so a verdict is an exit code, not an opinion |
| Verified result | [stages claimed under `harness run --all --mode isolated`], [spec tests], [mutation score] |
| Cost | [$ total, tokens per seat, wall time] from the ledger |
| Limitation | see [Limits](#limits) |

## Stand it up in 10 minutes

You need Linux with Docker, Python 3.12 (`uv`), Node 20, a Claude Code login and a BAND account. A Featherless key is optional (it moves the three verification seats to open models).

```bash
git clone <this repo> && cd <repo>
make setup                       # venv, Playwright, OpenCode provider config
cp .env.example .env             # add BAND_USER_API_KEY and GEMINI_API_KEY
```

Register five seats on one BAND account with BAND's helper (`scripts/register-agent.sh` from `band-ai/add-band`), named Planner, Redline, Builder, Adversary and Verifier, and put each `BAND_AGENT_ID_<SEAT>` / `BAND_API_KEY_<SEAT>` pair in `.env`. Then:

```bash
make preflight                   # 5 distinct seats on one account, mandate headers, live model probes, Docker, harness
make seed REPO=/abs/result       # fresh result repo with factory, mandates, venv; tagged factory-seed
make band REPO=/abs/result       # OpenCode server + five supervised seats (leave running)
make smoke                       # each seat must answer a tokened @mention
make dispatch-toy REPO=/abs/result   # or paste plan/dispatch.md into a new room
```

To point the factory at a different problem, write a new dispatch. Nothing in `mandates/` or `factory/` changes.

`make preflight` also writes [plan/readiness.md](plan/readiness.md), a dated table of every check it ran.

## Seats

Each seat is a BAND SDK agent run by `factory/seat.py`, with its mandate file as standing instructions. Claude Code seats use the Claude Agent SDK on a normal `claude` login; OpenCode seats talk to a local `opencode serve`. (`factory/seat.py` also runs Codex seats in a workspace-write sandbox; we dropped them when the plan's quota ran out.) Neither ever waits for a human: Claude seats run in `dontAsk` mode against an allowlist in `.claude/settings.json` (git, docker, python, tests, edits; push, amend, rebase and `rm -rf` denied), and OpenCode seats auto-accept tool calls and auto-reject questions addressed to a person.

| Seat | Model | Why this model here | Edit boundary |
|---|---|---|---|
| Planner | claude-opus-5 | long specs, careful requirement extraction, few calls | `plan/` |
| Redline | claude-opus-5 | tests are the thesis, so the strongest model writes them; never the builder's model, never sees the code | `stage-*/tests/` (not adversarial/, repro/) |
| Builder | claude-sonnet-5 | most tool calls of any seat; strong at code | stage folders, never others' tests |
| Adversary | claude-sonnet-5 | attacks need tool fluency (storms, curl, threads) more than depth | `stage-*/tests/adversarial/` |
| Verifier | claude-opus-5 | judgment matters: in rehearsal a Haiku verifier issued a BLOCK and a GO the gates did not support; never the builder's model, and `factory.record` refuses a GO the gate results do not back | nothing; commits gate output only |

`factory/seats.yaml` holds this table, including a fallback list per seat and an `effort` level (medium for the builder and adversary, whose work is iterative; high for the judgment seats). When a model is rate-limited or over a usage limit, the seat's supervisor waits with exponential backoff and moves to the next model (Opus seats fall back to Sonnet or Haiku, Sonnet seats to Opus). The governor never routes a limit to a person.

## How work moves

Every handoff is an @mention, because a BAND seat only wakes when addressed; seats never mention themselves (BAND answers 422). Handoffs paste the requirements instead of pointing at earlier messages, and each carries an evidence block:

```json
{"req": ["R-1-003", "R-1-005"], "commit": "9f3c2e1d4a7b", "ran": "python -m factory.gates.run stage-1 --gates 1,2,4,8",
 "result": {"exit": 1, "passed": 41, "failed": 1}, "log": "evidence/gates/s1/n1-g4-….log",
 "cost": {"tokens": 41000, "usd": 0.62, "seconds": 372}, "verdict": "NEEDS_WORK"}
```

Per stage: requirements (`plan/sN-requirements.md`, invariants first) → tests and gate hook → one item at a time → attack → gates → GO → next item. When every item has GO the verifier runs the full stage gates; on GO the stage folder is frozen and copied forward with `factory.stage_copy`, which never carries a nested `.git`.

## Gates

All gates are scripts in `factory/gates/`. Each exits 0 or 1, writes a log under `evidence/gates/`, and appends a `gate_result` event to the ledger, credited to the seat that ran it. A gate that crashes records a failure instead of stopping the run. With `--commit <sha>` the runner checks that exact commit in a private git worktree, so the verifier never moves the working tree the other seats are editing. Services run the way judges run them: `docker build`, then `--internal` network (no outbound), 2 vCPU, 2 GiB, `PORT=8080`.

| Gate | Fails when | Command |
|---|---|---|
| 1 Clean build | no Dockerfile/RUN.md, build fails, or no healthy answer within 60 s offline | `python -m factory.gates.g1_clean_build stage-N` |
| 2 Spec tests | any test fails, errors or skips; zero tests; fewer tests than any earlier run of this or an earlier stage | `…g2_spec_tests stage-N` |
| 3 Public checks | the task harness, isolated, does not claim the stage (one gate of eight, never the target) | `…g3_public_checks stage-N --track … --kickoff …` |
| 4 Invariant storm | any 5xx, transport error, or broken invariant over 1,000+ concurrent operations with 30% replays | `…g4_storm stage-N` |
| 5 No regression | an earlier stage's tests fail here, or state populated on the previous stage changes across the upgrade | `…g5_regression stage-N` |
| 6 Mutation bite | the unmutated code is not green first, or fewer than 80% of mutants are killed (flipped comparisons and arithmetic, swapped booleans, changed rounding, dropped locks) | `…g6_mutation stage-N` |
| 7 UI quality | overflow at 375/768/1280 px, a control under 24 px, a serious axe violation, an external asset, or a missing empty/loading/error state | `…g7_ui stage-N` |
| 8 Budget | an item over its attempts, minutes, tokens or spend; a stage over its minutes or spend (`factory/budget.yaml`) | `…g8_budget stage-N --node ID` |
| Scope | a commit by a non-seat, or a path outside its author's boundary; any deleted test | `python -m factory.scope A..B` |

The invariant is not in the factory. @Redline writes `tests/invariants/hook.py` from the dispatch (`setup`, `operation`, `invariant`, optional `populate/snapshot/carry` for upgrades and `UI_ROUTES` for gate 7), so the same gates protect a counter, a booking table or a ledger.

What the gates caught in the plumbing rehearsal (scripted seats, real gates, `proof/rehearsal/`): a retry check placed outside a lock passed all spec tests and failed the storm; the adversary's permanent test then turned gate 2 red until the fix; a builder edit that removed a concurrency test was blocked by the scope check and the test ratchet; two failed start-up attempts tripped the governor, which descoped the item instead of retrying forever.

## The record

Three files hold everything a judge or another team needs to audit a run, and all three are generated:

| File | What it holds | Written by |
|---|---|---|
| `evidence/ledger.jsonl` | one JSON event per line: `gate_result`, `verdict`, `handoff`, `cost`, `stage_closed`; each stores the SHA-256 of the line before it | gate scripts, `factory.record`, `factory.ingest` (from the room) |
| `evidence/run.html` | a replay of the room: every message with its evidence chips, the stage stepper, the reviews that changed the work, and the count of human messages after the dispatch | `python -m factory.viewer` |
| `evidence/dossier/stage-N.html` | one printable page per stage: gates, reviews with the diff each forced, cost by seat, with the source of every figure | `python -m factory.dossier` |

`python -m factory.ledger evidence/ledger.jsonl` re-checks the hash chain; an edited or deleted line breaks it.

## Results, cost and catches

The block below is generated by `make report` from the ledger, the room and git history. No number in it is typed by hand.

<!-- report:start -->
[Filled by `make report REPO=…` after the official run: results per stage, cost and time per seat per stage, the rejection ledger with the diff each rejection forced, what each gate caught, and who did the work.]
<!-- report:end -->

## Genericity proof

The same five mandates build the toy track in a separate room. Rehearsal result (`proof/toy/`): toy `stage-1/`, written by the band from the spec without opening the shipped tests, **passes 100% of the toy's complete stage-1 suite under `harness run --mode isolated`**, and correctly fails the stage-2 suite (no overshoot). We stopped that run after stage 1 to save usage for the judged run; its room replay is `proof/toy/run.html` and its cost table `proof/toy/report.md` ($1,603.79 list-price-equivalent, measured from the seat logs). [Full-toy score after the judged run.] `make scan` checks `mandates/` and `factory/` against both tracks' identifiers (from the task harness), a list of product nouns, and stage numbers used as requirements: 0 hits.

## How bad work is caught and recovered

A rejection names the failing gate, the log and the smallest repro, and goes to the author with @Planner copied. The fix comes back as a new commit, and the verifier re-runs every gate from scratch. A breach from @Adversary is a failing test in the repo, so no seat can accept work over it. When an item keeps failing, gate 8 trips and @Planner descopes it and moves on. Seats append generic root causes to `plan/lessons.md` and read it before each item. A seat process that dies is restarted by its supervisor; it rejoins the room and continues from the repository and its messages.

## Troubleshooting

Every row happened to us during rehearsal.

| Symptom | Cause | Fix |
|---|---|---|
| A seat never answers an @mention | it was not mentioned by its exact handle, or its process is down | `make smoke`; check `~/.cache/redline/logs/<seat>.log` for `online with` |
| A Claude seat answers but cannot edit or run anything | the result folder is not a trusted workspace, so its `.claude/settings.json` allowlist is ignored | run `claude` once in the result folder and accept |
| A seat stalls with `quota` / `usage limit` in its log | the model's plan or free tier ran out | the supervisor backs off and moves down the seat's fallback list; add a fallback or a key |
| Two planners work the same repo | a second dispatch was sent | `factory.dispatch` refuses a second send for 12 h; close the extra room |
| Seats act on an old task after a restart | they rejoin every room they belong to | `python -m factory.smoke --close <room ids>` before a new run |
| `git log` shows the human as committer | seat processes inherited the global git identity | start seats with `make band` (sets per-seat author and committer); the scope check flags mismatches |
| Gate 1 passes on your machine, fails for judges | the service fetches something at run time | gates run with no outbound network, exactly like judging; fix the Dockerfile |

## Failed experiments

Kept in full in [plan/failed-experiments.md](plan/failed-experiments.md). The ones that changed the design:

| Tried | What happened | Change |
|---|---|---|
| Free non-Claude models for the verification seats | Gemini flash 20 requests/day, Gemma 4 16k input tokens/min, Groq 8k tokens/min, Codex quota exhausted: each stalled a seat within its first turns | all seats on Claude Code, different models per role; Featherless optional |
| Codex seats in a workspace-write sandbox | `.git` read-only, so another seat committed under its name; every band commit showed the human as committer | per-seat git author and committer; scope check flags committer ≠ author |
| Mandate wording "split long handoffs" | our scanner flagged a product noun | reworded; scanner runs in preflight and CI |
| Scope check from the seed tag | one reverted violation kept every later check red | check from the last GO; owner-restored paths clear |
| Test-count ratchet per stage | deleting a test right after copy-forward went unnoticed | ratchet across this and earlier stages |
| Pasting run commands as one block | a second dispatch went out; two planners on one repo | dispatch refuses a second send for the same run; band runs detached |
| Launching seats from the development session | refused by its safety policy until the human added allow rules for `make band`/`smoke`/`dispatch` | the factory is driven only through those make targets |

## Limits

- Gates reach containers by IP on an internal Docker network, which works on Linux; on macOS run them inside a Linux VM.
- Seat token counts come from the seats' own evidence blocks, which are estimates; Claude subscription usage has no per-seat bill, so dollar figures for those seats are list-price estimates.
- All seats share one Claude subscription's usage limits; a limit pauses work (the supervisor backs off and retries) rather than ending it. We measured every free alternative and none sustained a seat: Gemini flash 20 requests/day, Gemma 4 16k input tokens/minute, Groq 8k tokens/minute, Codex quota exhausted. `factory/seat.py` still runs OpenCode and Codex seats; a Featherless key moves the three verification seats to open models with no code change.
- Gate 6 samples 12 mutants per run by default, a spot check rather than full mutation testing.
- [What the official run did not finish, stated plainly.]
