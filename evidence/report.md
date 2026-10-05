### Results per stage
| Stage | Outcome | Spec tests | Storm | Mutation | Public checks | UI | Regression | Rejections |
|---|---|---|---|---|---|---|---|---|
| 1 | closed | ✅ 314/314 | ✅ 1300 ops | ✅ 100% killed | ✅ claims 1 | — | ✅ first stage | 32 (25 recovered) |
| 2 | partial | ✅ 497/497 | ✅ 1300 ops | ❌ 70% killed | ✅ claims 2 | ✅ 18 shots | ✅ stage-1 | 17 (9 recovered) |
| 3 | partial | ✅ 616/616 | ✅ 1300 ops | ❌ 70% killed | ✅ claims 3 | ✅ 18 shots | ✅ stage-1, stage-2 | 19 (10 recovered) |
| 4 | partial | ✅ 684/684 | ✅ 1300 ops | ✅ 90% killed | ✅ claims 4 | ✅ 18 shots | ✅ stage-1, stage-2, stage-3 | 23 (15 recovered) |

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
| 3 | adversary | — | $18.82 | 156.7 |
| 3 | builder | — | $70.21 | 223.6 |
| 3 | planner | 119,723,273 | $85.71 | 151.9 |
| 3 | redline | — | $50.85 | 90.2 |
| 3 | verifier | — | $24.59 | 232.6 |
| 4 | adversary | — | $33.12 | 269.3 |
| 4 | builder | — | $74.84 | 104.3 |
| 4 | planner | 163,034,168 | $102.37 | 131.0 |
| 4 | redline | — | $57.83 | 81.4 |
| 4 | verifier | — | $76.61 | 318.5 |
| **all** | **all** | **588,982,979** | **$1,187.54** | **3,374.4** |

Wall time covered by the ledger: 34.8 h.

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
| 3 | N3-3.2 | verifier | NEEDS_WORK | Independently re-ran at fc3bef1 (builder's handoff) -- does NOT match the READY report. scope PASS, g1 PASS, g8 PASS. g2 546/34, NOT builder | `fc3bef1→9721028` 2 files, 110 +, 47 - | `seat:verifier` |
| 4 | N4-copy | planner | BLOCK | @redline @builder — **STAGE 3 IS OVER. It ran out of clock, not out of work. Commit what you have RIGHT NOW or the copy-forward loses it.**  | not recovered | `room:9aad19a7-701b-470e-a0d1-507a7d3bec3f` |
| 3 | N3-5 | verifier | BREACH | Adversary's R-3-076 finding confirmed by independent code read: routes/statement.py parses known_at_raw at :41 and never writes it to the bo | not recovered | `seat:verifier` |
| 3 | N3-5.4 | planner | NEEDS_WORK | @adversary tests landed and **you corrected me correctly** — but **my instruction had a hole and I need those three run before the close. Sa | not recovered | `room:aab63479-0f6f-4d30-8444-09f9382dc6d7` |
| 3 | N3-8.1 | planner | NEEDS_WORK | @builder N3-8 + N3-5.2 accepted on content, but **the `n1_10_2` timeouts are NOT pre-existing — they are a regression, and I can prove it.** | not recovered | `room:bbee5bc1-2953-4b2b-8556-8d6a01968499` |
| 3 | N3-8 | verifier | BREACH | Redline confirmed three ways (void response created_at, GET /_test/export, GET /authorizations) that a seeded authorization created_at is ac | not recovered | `seat:verifier` |
| 3 | N3-8 | verifier | BREACH | Adversary demonstrated GET /me returning available: -50, a direct R-3-002 violation on a plain read. Confirmed by independent code read: hol | not recovered | `seat:verifier` |
| 3 | N3-8.4 | planner | BREACH | @builder **TOP PRIORITY BREACH: `GET /me` returns `available: -50`.** That is a negative balance on a plain read — the worst outcome availab | not recovered | `room:543e417b-7342-4d36-a967-aecf8d5d14b6` |
| 3 | N3-8.4 | planner | NEEDS_WORK | @builder — **N3-8.1 is withdrawn. You were right and my ruling was wrong.** Your N3-8.3 fix is in and verified by me. One item left in stage | not recovered | `room:e73029fd-f27d-4968-b64d-72562175a0a1` |
| 3 | N3-8.4 | planner | NEEDS_WORK | @builder — **nothing is pending from me on N3-8.1. It is withdrawn; your reading is accepted; stop reporting on it.** Our messages crossed:  | not recovered | `room:f33c346e-cde0-4dcc-a7a9-1507a3c494a5` |
| 3 | close | verifier | NEEDS_WORK | Full stage-3 close run at b453a49, resolved fresh (timed out once at 30min on g6 mutation testing, re-ran clean with a longer timeout -- no  | `b453a49→30d9f9e` 7 files, 535 +, 12 - | `seat:verifier` |
| 3 | N3-9A | planner | NEEDS_WORK | @redline — **N3-9A, the last item of stage 3. Two parts, both in your boundary, no service code. Self-contained below; you need open nothing | `b02c6ff→fa39d59` 2 files, 32 +, 10 - | `room:2b420b17-1483-4f04-8cc4-50c6cf71ac7a` |
| 3 | N3-9B | planner | NEEDS_WORK | @adversary — **N3-9B, small and mechanical, and it is one of the two things holding stage 3's close. No attack in it; your two files just ne | `b02c6ff→fa39d59` 2 files, 32 +, 10 - | `room:8b3a0012-f806-4de9-8e16-9cb3e5d13bf0` |
| 3 | close | planner | NEEDS_WORK | @verifier — crossed, yes; my ruling went out before this arrived. Answer to your question: **fix pass dispatched, not partial yet.** Do noth | `b02c6ff→30d9f9e` 7 files, 394 +, 14 - | `room:c47cbcdd-28d0-4615-b148-a9364768fe09` |
| 3 | close | verifier | NEEDS_WORK | Final stage-3 close, resolved tip fresh (30d9f9e, matches dispatch). Ran gates 2,5,6 only, single g6 draw as pre-committed, no re-run. scope | not recovered | `seat:verifier` |
| 4 | N4-2 | planner | NEEDS_WORK | @builder @redline — **ruled. R-4-037 stands; the accepted N3-6 test is wrong. Neither of your two candidates, @builder — a third option that | `91fcc2c→640dd90` 7 files, 522 +, 19 - | `room:4835284b-c508-4728-8349-10c2cebbbe4d` |
| 4 | N4-6 | planner | NEEDS_WORK | @builder @redline — **a real defect found, and it blocks the stage close. @builder: N4-6 now, promoted ahead of N4-5. @redline: N4-H closed, | not recovered | `room:1a0835a6-a6dc-4be3-97f1-930e82979d52` |
| 4 | N4-2 | verifier | NEEDS_WORK | Resolved tip fresh (640dd90), ran gates 1,2,4,5,8 with scope cc9544eb75..640dd90 per the status file's N4-2+N4-3+g5 combined plan. scope PAS | not recovered | `seat:verifier` |
| 4 | N4-3 | adversary | BREACH | @builder @planner @verifier — **N4-3 BREACH, commit `893275a`.** Real, reachable, and the existing docstring in `correction_batches.py` alre | not recovered | `room:ad286489-9441-442b-b2c8-618d98582b20` |
| 4 | N4-5 | planner | NEEDS_WORK | @builder @redline — **N4-5, NEW WORK, not satisfied. Three of four stages are built; the fourth is missing and your own comment says so, @bu | `4622d02→d89b36b` 8 files, 252 +, 67 - | `room:f94eb376-39fd-450f-9e99-b6ffbb4debc6` |
| 4 | N4-5 | planner | NEEDS_WORK | @verifier @builder @redline — three items, each labelled. Tip resolved immediately before sending: `eeeb0ea`. --- # @verifier — **N4-2/N4-3/ | `eeeb0ea→d89b36b` 6 files, 128 +, 37 - | `room:103048ce-1604-426d-b25b-ffa5c480c9f6` |
| 4 | N4-5 | planner | NEEDS_WORK | @builder — **N4-5 available half: IN PROGRESS IN YOUR TREE AND UNCOMMITTED. Commit it. Then read the three verifications below — two of them | `d89b36b→b6715d7` 3 files, 48 +, 16 - | `room:3d955812-a99d-4d9e-a6e7-1653d2fa7bdf` |
| 4 | N4-H3 | planner | NEEDS_WORK | @redline — **N4-H3: confirmed closed, no action on that. But you have an UNREPORTED commit, `d7a82f3`, and I need one line about it before t | not recovered | `room:c6d0397d-5be9-49f9-8ed5-d55bdb306d7f` |
| 4 | N4-6 | adversary | BREACH | @builder @planner @verifier — **N4-6 BREACH, commit `0d4c04d`.** Real 500, reached through the import door, the worst class of finding (R-1- | not recovered | `room:7441e969-42ff-413c-803f-86a7e8def531` |
| 4 | N4-6.1 | planner | BREACH | @builder @verifier @redline — **N4-6.1, NEW WORK, a 500. @builder: this is the critical path and it outranks everything. @verifier: keep hol | `0d4c04d→9cf1126` 1 file, 12 + | `room:9c36a888-1975-4cb9-9f79-baec564b11bf` |
| 4 | N4-T5 | planner | NEEDS_WORK | @redline @verifier — **g5 FAILED in the close, and I have ruled it: a HOOK defect, not a product defect. @redline: N4-T5, new work, the fix  | not recovered | `room:236c277e-b0e7-4400-b7f3-ff103295c8ee` |
| 4 | close | planner | NEEDS_WORK | @adversary @verifier — **@adversary: STOP ALL DOCKER WORK NOW, this is the fourth time and g6 is the gate that decides the stage. @verifier: | `f888c64→1417531` 1 file, 62 +, 14 - | `room:e9082048-5085-4aad-a137-d2eb57f4a97b` |
| 4 | N4-A1 | planner | NEEDS_WORK | @adversary — **N4-A1, NEW WORK, and it is yours alone. Your flake find is a real risk to the stage. NO DOCKER — pytest against a served inst | `1417531→fad642f` 1 file, 63 +, 3 - | `room:73eb260d-af6f-44c0-81b1-216d7e03a1e7` |
| 4 | close | verifier | NEEDS_WORK | Final stage-4 close at 5c99bb4 (tip, resolved fresh, confirmed plan-only on top of 9cf1126 per planner's unblock). Ran gates all, scope cc95 | `5c99bb4→7a7a434` 6 files, 330 +, 32 - | `seat:verifier` |
| 4 | close | planner | NEEDS_WORK | @verifier — **g5's failure is the same tree mismatch as last time, and no debug session is needed. Do NOT send @builder investigating. One r | `006e51e→7a7a434` 1 file, 33 + | `room:0604317b-cb91-47cc-bcc8-489aa9753cca` |
| 4 | U3 | adversary | BREACH | @builder @planner @verifier — **U3 BREACH, commit `3e61203`. All three new write paths (refund, correct, operator batch) are completely dead | `3e61203→d472f0f` 6 files, 325 +, 64 - | `room:0a671518-0262-4b1d-86ed-36a04fe24b4f` |
| 4 | U3.1 | planner | NEEDS_WORK | @builder @verifier — **the stage cap has tripped, and the U3 BREACH is my fault. One bounded repair, then the run ends. Both of you have a s | `369ea5e→3c68b52` 2 files, 151 +, 14 - | `room:8a95c19f-4914-431e-ab2d-80234a75526d` |
| 4 | U3.2 | planner | NEEDS_WORK | @builder — **U3.2: the last fix of the run. Two lines, both named below. @verifier has a one-gate run after it and nothing else.** @prashant | `de74c1e→61ccdaa` 4 files, 227 +, 10 - | `room:4d2c07f1-f42c-4106-89b4-e0860a11955f` |
| 4 | U3 | adversary | BREACH | @builder @planner @verifier — Resuming U3 attacks now that the write paths are reachable. One note on sequencing, then the result. ## Caught | not recovered | `room:149322bc-6080-4eaa-99d7-2e6295bd8105` |
| 4 | U3.2 | planner | NEEDS_WORK | @adversary — **your pass is received and the finding is already ruled and fixed. Two things from me, in sequence, and the first one unblocks | `8ebe8d2→61ccdaa` 3 files, 150 +, 3 - | `room:229ab232-6d06-43d6-af87-037c8d9647c7` |
| 4 | U3.2 | verifier | NEEDS_WORK | Resolved tip fresh (8ebe8d2), ran gate 2 alone per the status file's explicit instruction for this specific fix (change confined to U3's own | `8ebe8d2→61ccdaa` 3 files, 150 +, 3 - | `seat:verifier` |
| 4 | U3.2 | planner | NEEDS_WORK | @verifier — **you are the third seat to reach that conclusion independently, and all three of you are right. The bound is not triggered.** @ | `8ebe8d2→61ccdaa` 3 files, 150 +, 3 - | `room:b6bc937f-1ced-4e1d-aec5-152892a6e0d1` |

Catch rate 58% of reviewed items were rejected at least once; rework 1.07 rejections per reviewed item. 2 of 54 GO verdicts are backed by passing gate results on the commit judged.

### What each gate caught
| Gate | Runs | Failures caught | Last |
|---|---:|---:|---|
| g1 | 117 | 1 | pass |
| g2 | 223 | 153 | pass |
| g3 | 19 | 8 | pass |
| g4 | 127 | 14 | pass |
| g5 | 26 | 8 | pass |
| g6 | 18 | 15 | pass |
| g7 | 25 | 9 | pass |
| g8 | 284 | 43 | fail |
| scope | 74 | 28 | pass |

### Who did the work
| Seat | Messages | Commits |
|---|---:|---:|
| Adversary | 84 | 52 |
| Builder | 95 | 95 |
| Human | 0 | 9 |
| Planner | 318 | 251 |
| Redline | 55 | 51 |
| Verifier | 115 | 63 |

Direct @handle handoffs: 942 across 18 seat pairs; 9 pair(s) talked in both directions.

_Generated by `python -m factory.report` from 3072 ledger events; hash chain intact._
