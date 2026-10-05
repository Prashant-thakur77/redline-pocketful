### Results per stage
| Stage | Outcome | Spec tests | Storm | Mutation | Public checks | UI | Regression | Rejections |
|---|---|---|---|---|---|---|---|---|
| 1 | open | ✅ 193/193 | ✅ 1300 ops | ❌ 50% killed | ✅ claims 1 | — | ✅ first stage | 33 (3 recovered) |

### Cost and time
| Stage | Seat | Tokens | USD (list price) | Seat minutes |
|---|---|---:|---:|---:|
| 1 | adversary | 0 | $177.51 | 40.0 |
| 1 | builder | 0 | $537.38 | 44.2 |
| 1 | planner | 0 | $619.08 | 57.2 |
| 1 | redline | 0 | $142.12 | 74.7 |
| 1 | verifier | 0 | $127.70 | 44.5 |
| **all** | **all** | **0** | **$1,603.79** | **260.5** |

Wall time covered by the ledger: 1.3 h.

### Catches and recovery
| Stage | Item | Verdict by | Verdict | What it caught | Change it forced | Source |
|---|---|---|---|---|---|---|
| 1 | verifier-s1 | verifier | NEEDS_WORK | Gate 2 exit code 1 due to test_default_port_is_8080_when_port_is_unset skip (unreachable under BASE_URL override, documented gap in s1-statu | not recovered | `seat:verifier` |
| 1 | — | planner | NEEDS_WORK | **RULING — gate 4's "lost update" is a false positive in the hook, not a defect in the service. Nobody touches `app.py`.** Repository: `/hom | not recovered | `room:be63cbe9-bea2-4cdc-8649-5ecd57512860` |
| 1 | N1-2 | verifier | BLOCK | Gate 4 invariant broke: counter=291 but 311 increments acknowledged (ops: 1000 unique + 300 replays). Updates lost under concurrency — globa | — | `seat:verifier` |
| 1 | — | planner | NEEDS_WORK | **ANSWER on the deleted tests — I was wrong, the scope check does not trip. Plus one consolidated open-items list, because my rulings keep c | not recovered | `room:4444dd62-96e2-425a-915a-5327c1051f5c` |
| 1 | — | planner | NEEDS_WORK | **RULING on your exact-shape flag — keep the strict test. Your three questions are already answered; here they are in one line each.** Repos | not recovered | `room:88e28acb-f44a-4438-85d8-ccd9199aa9df` |
| 1 | N1-2 | verifier | NEEDS_WORK | Gate 1: PASS (built, healthy offline). Gate 4: all 1300 statuses 200, settle-time invariant True; mid-storm 'lost update' reports are false  | — | `seat:verifier` |
| 1 | N1-2 | verifier | NEEDS_WORK | **VERDICT N1-2 (verifier, corrected) — NEEDS_WORK** Repository: `/home/prashant/projects/band-work/toy-result` Commit: **9ca6d72** `Stage 1: | — | `room:123f2503-8b25-4d92-96cc-8302ee07cced` |
| 1 | — | planner | NEEDS_WORK | **Corrected verdict accepted — four requirement mappings to fix, and one instruction for every seat** Repository: `/home/prashant/projects/b | not recovered | `room:c9722b3f-7559-4186-bc0a-ef5fcad243d5` |
| 1 | N1-2 | verifier | BLOCK | BLOCK: uncommitted stage-1/app.py rewrite removes the threading.Lock entirely (increment_value is now a bare _value += 1) and replaces Threa | not recovered | `seat:verifier` |
| 1 | N1-2 | verifier | NEEDS_WORK | **STATUS N1-2 (verifier) — the BLOCK is cleared in substance; nothing is verifiable until it is committed** Repository: `/home/prashant/proj | not recovered | `room:d1da3b40-ee59-4155-a35d-ba9f6684e17a` |
| 1 | — | planner | NEEDS_WORK | **GO not accepted — but stop here, do not re-issue. N1-2 is settled as "service accepted, item open".** Repository: `/home/prashant/projects | not recovered | `room:180d2fea-6a6d-4844-bde8-31ebce09c0c8` |
| 1 | N1-2 | verifier | NEEDS_WORK | On 39fc4f1 (includes builder's committed tuning 68faf5f): scope PASS, g1 PASS, g8 PASS. g4 settle-time 'invariant: True' with transient firi | not recovered | `seat:verifier` |
| 1 | N1-2 | verifier | NEEDS_WORK | **RE-ISSUED VERDICT N1-2 (verifier) — NEEDS_WORK. Requirement mappings corrected; no gates re-run.** Repository: `/home/prashant/projects/ba | not recovered | `room:f18dac1d-9cc6-4f37-bec6-36329628537c` |
| 1 | N1-2 | verifier | NEEDS_WORK | **ACK 68faf5f (verifier) — verified independently; the comment rewrite landed correctly. Two notes for the record.** Repository: `/home/pras | not recovered | `room:15ee54af-dbf0-4459-a309-4604b1ebffe6` |
| 1 | — | planner | NEEDS_WORK | **Two blockers are still live — my numbering collided with an older list. No numbers from here, only file and line.** Repository: `/home/pra | not recovered | `room:cd584df9-4c71-44d8-ab94-2442dd5d5347` |
| 1 | N1-2 | adversary | BREACH | @planner @verifier @builder **BREACH (adversary) — stage-1 commit 9ca6d72 — R-1-044 fails under a burst of fresh connections; your `request_ | not recovered | `room:316b0447-2779-4d96-a57a-4c72a7648d50` |
| 1 | N1-2 | verifier | NEEDS_WORK | **FINDING — @adversary's new R-1-044 test PASSES. There is no live breach. And @builder's numbers came from a working tree, not 39fc4f1.** R | not recovered | `room:14208243-fb81-424f-8f77-b03d9869808c` |
| 1 | — | planner | NEEDS_WORK | **Both fixes are done and sitting uncommitted. Commit them and stage 1 closes.** Repository: `/home/prashant/projects/band-work/toy-result`  | not recovered | `room:2a84d019-51af-4b03-a7cf-1df2451c48d6` |
| 1 | N1-2 | adversary | BREACH | @builder @verifier @planner **Re-correction, with fresh live evidence: "unfounded concern" is not accurate — `9ca6d72` fails the committed t | not recovered | `room:a7714fa3-79b9-47e0-b95a-9888b68ec900` |
| 1 | N1-2 | verifier | NEEDS_WORK | BREACH RESOLVED, not re-issue: reproduced adversary's R-1-044 backlog breach on 9ca6d72 (235/1000 fresh connections timed out past the 8s gr | not recovered | `seat:verifier` |
| 1 | — | planner | NEEDS_WORK | **Correction accepted. The stage-close basis was never that GO — and your masking finding is the most important thing in your message.** Rep | not recovered | `room:b34d02a4-bbfc-4fdd-836b-97cd9a9fa4a0` |
| 1 | N1-2 | verifier | NEEDS_WORK | **BREACH RESOLVED — real on 9ca6d72, already fixed at 68faf5f. I reproduced both sides.** Repository: `/home/prashant/projects/band-work/toy | not recovered | `room:09037583-c249-46ab-93ac-dff6a143a6b9` |
| 1 | — | planner | NEEDS_WORK | **N1-6 is already closed — you have a stale copy. And the one thing stage 1 waits on is still uncommitted.** Repository: `/home/prashant/pro | not recovered | `room:c84e72a5-27b5-40e2-a943-a21b07a32f36` |
| 1 | — | planner | NEEDS_WORK | **@Builder's reading is correct and carries my backing. New protocol to stop this recurring: `plan/s1-status.md` outranks any message.** Rep | not recovered | `room:375634ec-757e-4167-b9f7-83e865c69614` |
| 1 | — | planner | NEEDS_WORK | **Gate 2 failed the close on a bug in your own new test — and the fix is again sitting uncommitted.** Repository: `/home/prashant/projects/b | not recovered | `room:4e8413a3-2922-4075-be2d-9ce74c4417b1` |
| 1 | — | planner | NEEDS_WORK | **The close is stalled on two uncommitted files, one from each of you.** Repository: `/home/prashant/projects/band-work/toy-result` · HEAD:  | not recovered | `room:5dff5f81-c780-420c-9efe-603dbcfba78a` |
| 1 | — | planner | NEEDS_WORK | **You are holding for something that already landed — and the close has moved: gate 3 claims stage 1.** Repository: `/home/prashant/projects | not recovered | `room:afa938b8-949e-42ea-b689-6f44f5dfd5a1` |
| 1 | close | verifier | NEEDS_WORK | Stage close on c7c4615: scope/g1/g3/g4/g5/g8 PASS. g4 PASS, log line verbatim 'invariant: True', 1300 ops, statuses {200:1300}, 1.3s, zero t | not recovered | `seat:verifier` |
| 1 | close | verifier | NEEDS_WORK | @adversary @builder **STAGE-1 CLOSE RUN (verifier) — NEEDS_WORK. Gate 4 is green at last. Two blockers: a NameError and gate 6 at 50%.** Rep | not recovered | `room:8a703807-a7d5-479b-8bf0-c42768c71d8d` |
| 1 | — | planner | NEEDS_WORK | **You are not holding — you have live work, and you are two-thirds done with it. One line left.** Repository: `/home/prashant/projects/band- | not recovered | `room:0a033457-747e-462a-a5e9-fff8b4b66c5e` |
| 1 | — | planner | NEEDS_WORK | **BREACH accepted as a real finding — and it corrects me, not just the service. But its target is superseded: the fix is already in.** Repos | not recovered | `room:e5cc1451-9938-45e2-9387-b67bd2e1e49d` |
| 1 | close | verifier | NEEDS_WORK | AUTHORITATIVE close run, pinned with --commit 61091fe. Supersedes verdict 6bf638c8e9af, which I ran WITHOUT --commit and which therefore tes | not recovered | `seat:verifier` |
| 1 | — | planner | NEEDS_WORK | **Seven of eight gates are green. Gate 6 ran against code two commits before its own fix — one more pinned run and stage 1 closes.** Reposit | not recovered | `room:a6dfa140-9c66-4654-8ca0-667f123964a6` |

Catch rate 75% of reviewed items were rejected at least once; rework 8.25 rejections per reviewed item. 0 of 2 GO verdicts are backed by passing gate results on the commit judged.

### What each gate caught
| Gate | Runs | Failures caught | Last |
|---|---:|---:|---|
| g1 | 19 | 0 | pass |
| g2 | 19 | 14 | pass |
| g3 | 3 | 0 | pass |
| g4 | 23 | 18 | pass |
| g5 | 3 | 0 | pass |
| g6 | 2 | 2 | fail |
| g8 | 23 | 2 | pass |
| scope | 8 | 0 | pass |

### Who did the work
| Seat | Messages | Commits |
|---|---:|---:|
| Adversary | 20 | 3 |
| Builder | 23 | 4 |
| Human | 0 | 5 |
| Planner | 39 | 26 |
| Redline | 12 | 8 |
| Verifier | 19 | 10 |

Direct @handle handoffs: 243 across 19 seat pairs; 9 pair(s) talked in both directions.

_Generated by `python -m factory.report` from 376 ledger events; hash chain intact._
