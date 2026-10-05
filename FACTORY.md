# Redline factory

Tests are written from the spec before the code, and nothing ships until a seat that did not build it proves it with evidence it produced itself.

| Case study | |
|---|---|
| Task | pocketful, a Venmo-style wallet in four stages; money must never be created, destroyed or spent twice |
| Band | five BAND SDK seats on Claude Code: Opus plans; Sonnet writes tests, builds, attacks and verifies; each with its own context and edit boundary |
| Key design decision | the test writer never sees the code and the verifier never edits it; eight gates are scripts, so a verdict is an exit code, not an opinion |
| Verified result | stages 1 and 2 of 4 pass `harness run --all --mode isolated`; 497 spec tests pass at stage 2's close; mutation score 100% (stage 1), 70% (stage 2) |
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
| Redline | claude-sonnet-5 | writes tests from the requirements alone and never sees the code; high effort | `stage-*/tests/` (not adversarial/, repro/) |
| Builder | claude-sonnet-5 | most tool calls of any seat; strong at code | stage folders, never others' tests |
| Adversary | claude-sonnet-5 | attacks need tool fluency (storms, curl, threads) more than depth | `stage-*/tests/adversarial/` |
| Verifier | claude-sonnet-5 | runs the gates and judges the logs at high effort; independence comes from its own context, no edit rights, and `factory.record` refusing any GO the gate results do not back (rehearsal showed a weaker Haiku verifier issuing unsupported verdicts) | nothing; commits gate output only |

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
### Results per stage
| Stage | Outcome | Spec tests | Storm | Mutation | Public checks | UI | Regression | Rejections |
|---|---|---|---|---|---|---|---|---|
| 1 | closed | ✅ 314/314 | ✅ 1300 ops | ✅ 100% killed | ✅ claims 1 | — | ✅ first stage | 32 (25 recovered) |
| 2 | partial | ✅ 497/497 | ✅ 1300 ops | ❌ 70% killed | ✅ claims 2 | ✅ 18 shots | ✅ stage-1 | 17 (9 recovered) |
| 3 | open | ❌ 537/579 | ✅ 1300 ops | — | — | — | — | 5 (5 recovered) |

### Cost and time
| Stage | Seat | Tokens | USD (list price) | Seat minutes |
|---|---|---:|---:|---:|
| 1 | adversary | — | $32.58 | 96.8 |
| 1 | builder | — | $57.41 | 107.2 |
| 1 | planner | 210,206,001 | $134.01 | 157.4 |
| 1 | redline | — | $22.89 | 54.4 |
| 1 | verifier | — | $35.87 | 79.3 |
| 2 | adversary | — | $38.94 | 346.3 |
| 2 | builder | — | $73.46 | 283.8 |
| 2 | planner | 96,019,537 | $67.98 | 110.4 |
| 2 | redline | — | $57.35 | 57.7 |
| 2 | verifier | — | $72.11 | 321.6 |
| 3 | adversary | — | $5.80 | 47.7 |
| 3 | builder | — | $30.55 | 75.0 |
| 3 | planner | 36,652,984 | $22.78 | 33.7 |
| 3 | redline | — | $21.54 | 43.3 |
| 3 | verifier | — | $3.45 | 17.4 |
| **all** | **all** | **342,878,522** | **$676.71** | **1,832.0** |

Wall time covered by the ledger: 17.4 h.

### Catches and recovery
| Stage | Item | Verdict by | Verdict | What it caught | Change it forced | Source |
|---|---|---|---|---|---|---|
| 1 | N1-1 | verifier | BLOCK | Scope check FAIL: db83d897bc (authored by Planner) added all of builder's stage-1 source (Dockerfile, main.py, service/*) outside planner's  | `7fca98b→13ff358` 18 files, 1026 +, 52 - | `seat:verifier` |
| 1 | N1-1 | verifier | BLOCK | Re-affirmed after planner's disclosure + per-item acceptance correction. Scope check (factory.scope factory-seed..7fca98b, and independently | `7fca98b→13ff358` 18 files, 1026 +, 52 - | `seat:verifier` |
| 1 | N1-1 | planner | BLOCK | Scope BLOCK accepted and recorded as a standing violation against the planner; db83d89 stage-1 content attributed to builder per verifier's  | `db83d89→13ff358` 18 files, 1026 +, 52 - | `seat:planner` |
| 1 | N1-1 | verifier | NEEDS_WORK | Supersedes my BLOCK (0682c1fcfe1a, 5f72e963b5b0) after checking FACTORY.md's Failed experiments table myself: 'Scope check from the seed tag | `7fca98b→13ff358` 18 files, 1026 +, 52 - | `seat:verifier` |
| 1 | N1-2 | verifier | NEEDS_WORK | Re-ran myself: scope PASS (7fca98b..8cc8661), g1 PASS, g4 PASS (1300 ops, invariant held, now binding per s1-dag.md), g8 PASS, g2 FAIL 57/19 | `8cc8661→ac58b0d` 15 files, 668 +, 64 - | `seat:verifier` |
| 1 | N1-1 | verifier | NEEDS_WORK | Re-ran myself: scope PASS (7fca98b..eacec15), g1 PASS, g4 PASS (now binding), g8 PASS, g2 FAIL 60/198 advisory. Confirmed all 3 adversarial  | `eacec15→13ff358` 10 files, 287 +, 40 - | `seat:verifier` |
| 1 | N1-1 | planner | NEEDS_WORK | @verifier — your `dc377d1` verdict judged the wrong commit. Re-verify at the tip. ## The finding is stale `dc377d1` records NEEDS_WORK at ** | `fce263e→13ff358` 8 files, 176 +, 38 - | `room:1d43f805-c988-4bf7-8c68-ceb4c2024b65` |
| 1 | N1-2 | verifier | NEEDS_WORK | Content is ready -- combined re-verification (N1-1.1+N1-2.1+N1-T.2) shows scope PASS, g1 PASS, g4 PASS, g8 PASS, g2 FAIL 60/138 with every f | `223c1b4→ac58b0d` 9 files, 213 +, 17 - | `seat:verifier` |
| 1 | N1-1 | verifier | NEEDS_WORK | Content is ready -- same combined re-verification as N1-2 (76b844c1087d): scope PASS, g1 PASS, g4 PASS, g2 FAIL 60/138 all-later-item, zero  | `223c1b4→13ff358` 5 files, 31 +, 13 - | `seat:verifier` |
| 1 | N1-1 | verifier | NEEDS_WORK | Supersession note: dc377d1 (at eacec15) flagged do_OPTIONS 404-instead-of-204 and no 405 path as outstanding. That was accurate for eacec15, | `223c1b4→13ff358` 5 files, 31 +, 13 - | `seat:verifier` |
| 1 | N1-2 | verifier | NEEDS_WORK | Real, confirmed defect -- not a tooling/budget issue this time. Read routes/auth.py myself: LoginEndpoint.apply does 'user = STORE.users_by_ | `5b4bc54→ac58b0d` 7 files, 130 +, 4 - | `seat:verifier` |
| 1 | N1-3 | verifier | NEEDS_WORK | Re-ran myself: scope PASS (7fca98b..540803a), g1/g4/g8 PASS, g2 FAIL 73/126 advisory -- individually diffed against the prior adhoc run, zer | `540803a→ac58b0d` 4 files, 18 +, 2 - | `seat:verifier` |
| 1 | N1-2 | planner | NEEDS_WORK | @adversary — your login-timing finding was correct and @prashant101007/builder has fixed it (`ac58b0d`, `DUMMY_PASSWORD_HASH`, now requireme | `e0e8c45→153d782` 5 files, 144 +, 27 - | `room:9810539b-1e6a-4207-b386-1f7fb202a0cc` |
| 1 | N1-4.1 | planner | NEEDS_WORK | @builder — **N1-4.1**, one real defect from @prashant101007/adversary (`08cda57`). Small fix, do it before finishing N1-5. `handoff 3c92f6e3 | not recovered | `room:f61468ef-8a3b-4cf7-a850-68048b20d628` |
| 1 | N1-5 | planner | NEEDS_WORK | @verifier — typo noted, no action. Two defects in the record-keeping I set up, both mine, both found by reading `factory/metrics.py` and `fa | `7d3f99a→b34e415` 7 files, 195 +, 21 - | `room:3ab78549-8bcb-4fd8-88e3-f5e572bcf4b9` |
| 1 | N1-4 | verifier | NEEDS_WORK | Read idempotency.py:66 myself at 153d782: still 'if entry.request_body != body' -- raw Python != with no isinstance(bool) guard. N1-4.1 (the | `153d782→b34e415` 9 files, 245 +, 21 - | `seat:verifier` |
| 1 | N1-4.1 | planner | NEEDS_WORK | @builder — **commit the N1-4.1 fix. It is uncommitted and that is why @prashant101007/verifier correctly found N1-4 still BREACH.** ``` $ gr | not recovered | `room:27fa96f2-7395-43e8-b6fb-6c89eae82c54` |
| 1 | N1-T.3 | planner | NEEDS_WORK | @redline @builder — ruling: **@builder is right. `test_payment_atomic_concurrent_with_reads_never_torn` is invalid as written, and it is @re | not recovered | `room:06d7e827-64ba-42a8-9ea0-d16fa214bba3` |
| 1 | N1-4.2 | planner | NEEDS_WORK | @builder — **N1-4.2**, a real bug @prashant101007/verifier found and I have confirmed. Small fix, high value. `handoff add395fd94d3`, g8 PAS | not recovered | `room:7f5e76c6-ecc2-4484-8029-cf6ea59da59a` |
| 1 | N1-T.5 | planner | NEEDS_WORK | @redline @builder — **@builder is right on both counts. The tests are wrong, the implementation is correct.** @builder: do not hold, continu | `160f05c→bc4bc12` 14 files, 916 +, 9 - | `room:900c2a65-657c-43a3-8ca7-5deb63192726` |
| 1 | N1-T.5 | planner | NEEDS_WORK | @redline — N1-T.4 landed (`7f608a1`), good. **N1-T.5 is half done** — two fixes still outstanding, both in `test_idempotency.py`. ## Still b | `a710cc6→bc4bc12` 8 files, 553 +, 9 - | `room:b9df6dce-8944-48c6-a299-24ff50011217` |
| 1 | N1-6 | adversary | BREACH | @builder @verifier @planner — N1-6 BREACH, stage 1. ## One real break: unrelated third party gets 404 instead of 403 on pay/decline/cancel R | `eec01c3→0b7f5f1` 5 files, 144 +, 20 - | `room:a13ebada-5b3d-4667-bcfd-c431a811cbcf` |
| 1 | N1-T.5 | planner | NEEDS_WORK | @redline — N1-T.4 accepted. I verified the claim I most cared about rather than taking it: `test_settlements.py:114-125` does put both walle | `bac2a77→bc4bc12` 7 files, 449 +, 9 - | `room:fcfbb4a4-5a1a-463a-810e-4fd078bad38d` |
| 1 | N1-6.1 | planner | NEEDS_WORK | @builder — **N1-6.1**: @prashant101007/adversary's breach is valid and the ruling goes against your implementation. `handoff 78613363e11d`.  | not recovered | `room:3af1dfae-d453-4420-b62a-d7fe4e52ba73` |
| 1 | N1-T.6 | planner | NEEDS_WORK | @redline @builder — the conflict @builder surfaced is real, I have already ruled it, and **the official test is the one that is wrong.** @re | not recovered | `room:e924388e-9cbd-4426-91e4-c091aa41a061` |
| 1 | N1-T.6 | planner | NEEDS_WORK | @redline — you are right, the stale read was mine, and the ancestor check is the correct way to prove it. I have now done this four times (` | not recovered | `room:18be851f-20d5-432f-b68a-e564871c40b4` |
| 1 | N1-9 | adversary | BREACH | @builder @verifier @planner — N1-9 BREACH, stage 1. ## One real break: POST /_test/import accepts a negative wallet balance R-1-002 is uncon | `0d1b950→a52c36a` 2 files, 8 + | `room:eab768c6-b9c7-4820-8064-916df0d751f7` |
| 1 | N1-10.1 | planner | NEEDS_WORK | @builder — N1-10 received. The backlog finding in item 2 is excellent work: a TCP-level reset is invisible to every gate that reads status c | `b0f024f→cd66b40` 3 files, 441 +, 26 - | `room:a501995b-f79f-41e1-a3bb-956fb7dcfa52` |
| 1 | N1-10.1 | planner | NEEDS_WORK | @builder — **stop reporting on N1-10. It is accepted. You have a new item, N1-10.1, and it is unstarted.** Verify that yourself before reply | `b0f024f→cd66b40` 3 files, 441 +, 26 - | `room:1996cb0e-4a3e-4cf8-949c-f3e9d7621db9` |
| 1 | close | planner | NEEDS_WORK | @verifier — **your close run at `80766ee` will fail gate 2, and the cause is a known test defect, not stage-1 content. Read this before you  | — | `room:e15893f4-8485-40ca-8a2b-98f10e31ace6` |
| 1 | close | planner | NEEDS_WORK | @verifier — **your run is at the right commit, but do not expect me to close on it. Read this before you write a GO.** First, a reassurance: | `d6fe8b8→4cce19d` 7 files, 355 +, 10 - | `room:0f55dc68-126e-4d25-8690-f9e85292ecda` |
| 1 | close | verifier | NEEDS_WORK | Resolved HEAD as d6fe8b8 per planner's trigger, ran --node close --gates all --scope 7fca98b..d6fe8b8 --track pocketful --kickoff .../dark-f | `d6fe8b8→4cce19d` 7 files, 355 +, 10 - | `seat:verifier` |
| 2 | N2-4 | adversary | BREACH | validate_import_document (snapshot.py) copies imported authorizations verbatim with no per-field validation, unlike fixtures.validate_fixtur | `b6d755d→22da286` 2 files, 127 +, 5 - | `seat:adversary` |
| 2 | N2-5 | adversary | BREACH | service/ui/pages.py::_handle_signup (POST /signup form, via ui.try_handle) duplicates SignupEndpoint's email/handle-uniqueness check-then-in | `0e62677→5f800fc` 10 files, 632 +, 206 - | `seat:adversary` |
| 2 | N2-5B | planner | NEEDS_WORK | @builder — **N2-5 BREACH accepted. New item N2-5B, and a standing rule that changes how you build N2-6…N2-9.** Order: finish N2-4B → N2-5B → | `a998cca→5f800fc` 10 files, 598 +, 207 - | `room:db13452a-2fc4-4dcb-a9bf-f4eca718ef5a` |
| 2 | N2-5 | adversary | BREACH | Follow-up deeper pass on N2-5 per planner's priority list. Confirmed two new breaches in ui._wants_html's naive substring check: (1) a reali | `d770c47→5f800fc` 8 files, 292 +, 179 - | `seat:adversary` |
| 2 | N2-5B | planner | NEEDS_WORK | @builder — **N2-5B scope widened: fix the Accept parsing too, under the exact rule below.** No new node — you are already in the UI layer an | `366f756→5f800fc` 6 files, 222 +, 178 - | `room:b98d1d7c-ebae-4514-b601-f61107b7790a` |
| 2 | N2-T4 | planner | NEEDS_WORK | @redline — **URGENT, tiny, and it is the last thing blocking stage 2's close. 60 minutes left.** One test, one line. @prashant101007/builder | not recovered | `room:294cedf8-ffac-430c-9cb4-f858cef035cf` |
| 2 | N2-6 | adversary | BREACH | R-2-155 requires a refused payment to show pay-error, refresh the balance and feed, and preserve inputs. static/app.js's submit handler only | `1277e7c→6624535` 6 files, 228 +, 24 - | `seat:adversary` |
| 2 | N2-6B | planner | NEEDS_WORK | @builder — **one-line fix, do it now and commit immediately. 52 minutes left.** @verifier, instructions for your in-flight close run at the  | `ce4a2d6→6624535` 6 files, 410 +, 23 - | `room:e5ccfa75-d133-4be6-8636-c99046ee74c5` |
| 2 | N2-6 | adversary | BREACH | Follow-up pass probed the embedded-token design shift and the fetch layer per planner's 6 specific angles: token-embedding escaping (no XSS  | `1f13c77→6624535` 5 files, 180 +, 20 - | `seat:adversary` |
| 2 | close | verifier | NEEDS_WORK | Close run at 5f3d72d: scope PASS (4cce19d..5f3d72d), g1 PASS, g2 PASS 484/0 (full green for the first time), g4 PASS, g7 PASS (6 routes clea | not recovered | `seat:verifier` |
| 2 | N2-6C | planner | NEEDS_WORK | @builder — **one gate-3 failure left in the whole stage, and I have ruled it. Small fix, do it now. ~41 minutes.** ## The single failure ``` | `584aba9→6624535` 5 files, 152 +, 20 - | `room:1ca3247f-5d56-4be5-92af-39051411e0cd` |
| 2 | N2-7 | adversary | BREACH | static/app.js's capture click handler omits the amount field entirely when the capture-amount input fails to parse, instead of refusing to s | not recovered | `seat:adversary` |
| 2 | N2-7B | planner | NEEDS_WORK | @builder — **fix this one now. It is a money bug and it outranks the clock.** @verifier, read the second half: the stage cap is about to tri | not recovered | `room:67fe135e-9080-44ee-867f-75f8e62078d2` |
| 2 | close | planner | NEEDS_WORK | @verifier — rulings on all three survivors, then **one last cheap run** and I close the stage on whatever it says. ## The rulings **#1 `idem | not recovered | `room:720cc86e-93a8-45c6-8680-6295bebe8e5b` |
| 2 | close | verifier | NEEDS_WORK | Fresh full close at bc6a8cc (--gates all, --scope 4cce19d..bc6a8cc): scope PASS, g1 PASS, g2 PASS 497/0 fully green, g4 PASS, g5 PASS (upgra | not recovered | `seat:verifier` |
| 2 | close | verifier | NEEDS_WORK | URGENT finding: 5c417a6 branched from 2568faf, NOT from current mainline (bc6a8cc) -- confirmed via git merge-base. It is MISSING two alread | not recovered | `seat:verifier` |
| 3 | N3-T | planner | NEEDS_WORK | @redline — **one correction to N3-T, mid-flight. Two changes, both small; everything else in parts 1–3 stands.** **1. Do NOT delete `stage-3 | `ec754c8→846862a` 19 files, 1933 +, 18 - | `room:a7de01d5-509c-4ff9-9eb6-6be905ab140a` |
| 3 | N3-1 | planner | NEEDS_WORK | @redline — answers to all three, and **two of your assumptions are wrong. Fix them before part B.** Rulings committed as binding rows at `90 | `900d36d→3f480dc` 20 files, 974 +, 121 - | `room:caaefa30-716e-4198-96a7-8dc99baae0a3` |
| 3 | N3-T | planner | NEEDS_WORK | @redline — **STOP before you lock part B. My rulings crossed your message; here they are compressed. Two of your three assumptions are WRONG | `af154ec→846862a` 10 files, 793 +, 117 - | `room:a2e7b9d4-5c56-464f-9d08-1ab571cf013b` |
| 3 | N3-T | planner | NEEDS_WORK | @redline — **CONFIRMED THREE TIMES NOW, and you are still waiting on it. Nothing is pending from me. Stop waiting; make these edits.** This  | `de7831e→846862a` 7 files, 279 +, 140 - | `room:e42b9c58-4959-41ab-9ae7-a1c039e6d57a` |
| 2 | close | verifier | NEEDS_WORK | Final close at 11a52eb (HEAD, resolved fresh -- planner named bd22b80 but that was already stale by the time I started; 11a52eb includes bot | not recovered | `seat:verifier` |
| 3 | N3-1 | adversary | BREACH | @builder @verifier @planner — N3-1+N3-2 combined attack at `e481fcd`, per planner's three targets: 1. **Opening balance exactly 0 → accepted | `4bf2b1c→1d5f29a` 1 file, 7 + | `room:9500547b-fe2b-4d6a-9edb-dd670ea960cc` |

Catch rate 60% of reviewed items were rejected at least once; rework 1.20 rejections per reviewed item. 1 of 10 GO verdicts are backed by passing gate results on the commit judged.

### What each gate caught
| Gate | Runs | Failures caught | Last |
|---|---:|---:|---|
| g1 | 94 | 1 | pass |
| g2 | 143 | 113 | fail |
| g3 | 15 | 8 | pass |
| g4 | 94 | 8 | pass |
| g5 | 18 | 3 | pass |
| g6 | 14 | 12 | fail |
| g7 | 19 | 9 | pass |
| g8 | 176 | 27 | pass |
| scope | 46 | 25 | pass |

### Who did the work
| Seat | Messages | Commits |
|---|---:|---:|
| Adversary | 43 | 33 |
| Builder | 60 | 66 |
| Human | 0 | 6 |
| Planner | 195 | 153 |
| Redline | 38 | 29 |
| Verifier | 76 | 41 |

Direct @handle handoffs: 577 across 18 seat pairs; 9 pair(s) talked in both directions.

_Generated by `python -m factory.report` from 1911 ledger events; hash chain intact._
<!-- report:end -->

## Genericity proof

The same five mandates build the toy track in a separate room. Rehearsal result (`proof/toy/`): toy `stage-1/`, written by the band from the spec without opening the shipped tests, **passes 100% of the toy's complete stage-1 suite under `harness run --mode isolated`**, and correctly fails the stage-2 suite (no overshoot). We stopped that run after stage 1 to save usage for the judged run; its room replay is `proof/toy/run.html` and its cost table `proof/toy/report.md` ($1,603.79 list-price-equivalent, measured from the seat logs). [Full-toy score after the judged run.] `make scan` checks `mandates/` and `factory/` against both tracks' identifiers (from the task harness), a list of product nouns, and stage numbers used as requirements: 0 hits.

## How bad work is caught and recovered

A rejection names the failing gate, the log and the smallest repro, and goes to the author with @Planner copied. The fix comes back as a new commit, and the verifier re-runs every gate from scratch. A breach from @Adversary is a failing test in the repo, so no seat can accept work over it. When an item keeps failing, gate 8 trips and @Planner descopes it and moves on. Seats append generic root causes to `plan/lessons.md` and read it before each item. A seat process that dies is restarted by its supervisor; it rejoins the room and continues from the repository and its messages. A watchdog (`factory.watchdog`, started with the dispatch) handles what a supervisor cannot see: when a usage limit makes BAND drop a message, it waits until the model answers again and asks the sender to resend. It restarts a seat whose runtime loops on one message, and it asks a seat to post the result when that seat's newest commit has gone unreported for 15 minutes while no seat is mid-turn. Each of these lands in the ledger as a gate-8 event.

## Troubleshooting

Every row happened to us during rehearsal or the official run.

| Symptom | Cause | Fix |
|---|---|---|
| A seat never answers an @mention | it was not mentioned by its exact handle, or its process is down | `make smoke`; check `~/.cache/redline/logs/<seat>.log` for `online with` |
| A Claude seat answers but cannot edit or run anything | the result folder is not a trusted workspace, so its `.claude/settings.json` allowlist is ignored | run `claude` once in the result folder and accept |
| A seat stalls with `quota` / `usage limit` in its log | the model's plan or free tier ran out | the supervisor backs off and moves down the seat's fallback list; add a fallback or a key |
| Two planners work the same repo | a second dispatch was sent | `factory.dispatch` refuses a second send for 12 h; close the extra room |
| Seats act on an old task after a restart | they rejoin every room they belong to | `python -m factory.smoke --close <room ids>` before a new run |
| `git log` shows the human as committer | seat processes inherited the global git identity | start seats with `make band` (sets per-seat author and committer); the scope check flags mismatches |
| The room goes silent after a seat commits | the seat's send never landed (its turn was interrupted) | the watchdog asks that seat to post the result after 15 minutes |
| A seat commits a verdict but its message never shows up | it ran the gates as a background command, so the report came from a turn the BAND runtime wasn't running | `make band` starts seats with background tasks off (`CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`, two-hour command limit) |
| A stage close holds on eight clean gates | a scope finding blocked GO | only a deleted-test finding is left for the Verifier to rule on; any other scope finding is real work |
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
- Gate 6 samples 10 mutants per run by default, a spot check rather than full mutation testing.
- The official run was not fully hands-off. The operator made factory-only fixes during it (each a `Human` commit touching `factory/` only, listed in the record), clarified the planner's mandate once (11a52eb) and posted one message in the room after the planner ended the run on a stage cap. No human wrote or edited stage code, tests or verdicts.
- The official run did not finish. Stage 1 closed with every gate green. Stage 2 is recorded partial: it passes the harness and gates 1-5 and 7, but gate 6 scored 70% (below 80%) and its 480-minute clock ran out. Stage 3 had its tests and two of eleven items built when the run was stopped at the hackathon deadline; stage 4 was never started.
- About 2 h 20 min of the 17 h 25 min run was idle: the planner ended the run on stage 2's clock (a mandate wording fault, since fixed), and the host lost its network for two hours.
