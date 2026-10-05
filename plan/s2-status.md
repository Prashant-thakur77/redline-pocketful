# Stage 2 status

Stage 1 closed at `4cce19d` (@verifier GO `9bfb5d357b8c`). `stage-2/` starts as a
copy-forward of the frozen `stage-1/`, so every R-1-001 … R-1-244 requirement arrives
satisfied and must stay satisfied — that is gate 5's job from here on.

| id | state | commit | evidence |
|---|---|---|---|
| N2-0 | **done** | `721295c` (+ `0ba3d8f` cost) | @builder. `git diff --stat 4cce19d:stage-1 721295c:stage-2` is **empty** — the trees are identical, nothing differs but the path prefix — and `stage-2/tests/invariants/hook.py`, `stage-2/Dockerfile`, `stage-2/RUN.md` are all present. @builder reported both checks rather than asserting the copy worked, and stopped without starting N2-1. |
| N2-T | **READY** | `36bcb2d` | 431 tests (up from stage 1's 314), 0 collection errors, red for the right reason (`httpx.ConnectError`, no service). Planner-verified below. |
| N2-1 | **HOLDS — closed on content, not on a gate-backed GO** | `15b99f5` (+ `f8c6462` code, `e3f81bb`/`5b6df67` attack) | Holds model. @adversary **HOLDS** (`a5a39df7c0a0`, 15 attacks). @verifier re-ran tagged: **g1 PASS, g4 PASS, g8 PASS**; scope clean but for the already-ruled sanctioned finding; collection ratchet **447 ≥ 431**. **No GO is possible for this item** — gate 2 cannot be green until the UI lands and `factory.record` rightly refuses a GO the gates do not back. See the ruling below; this is reported as HOLDS, never as GO. |
| N2-2 | **HOLDS — closed on content, gate 2 advisory** | `d2f2cba` (attack `bafc581`) | Authorization endpoints. @adversary **HOLDS** (`e676f9b34cc5`). @verifier: **g1 PASS, g4 PASS, g8 PASS**, `collect-only` 447, scope clean but for the sanctioned finding. The `405` prediction came true — **zero 405** in the mix. @verifier spot-checked the attribution by reading code (serve+pytest still sandbox-blocked) and found the two new adversarial failures to be a **genuine test bug**, not a defect. HOLDS, not GO, per the ruling below. |
| N2-3 | **HOLDS — closed on content, gate 2 advisory** | code `07052a8`, attack `0134811` | Capture and void. @verifier: **g1 PASS, g4 PASS, g8 PASS**, `collect-only` 447, scope clean but for the sanctioned finding; **the `404`-drop tripwire fired clean: zero `404`, down from 149.** @adversary then attacked the served `07052a8` directly — **18 attacks, HOLDS** (`0134811`): R-2-066 capture at `available == 0` succeeds (capture spends the wallet, never `available_for()`); R-2-056 partial final capture released exactly the remainder in the same step; R-2-005 capture-vs-void race over 15 trials had exactly one winner every time, landing only on `(0,0)` or `(1000,1000)`; a 15-way overcommit race on a 1000 remainder committed exactly ten 100s and returned `409 authorization_not_open` (never a stray `422`) for the rest; `403` beats `409` for a stranger on an expired hold; double void is idempotent. Gate 2 on the served commit: 409 passed, 48 failed, **zero in `test_n2_3_adversarial.py`** — the 48 remain the attributed UI/export-import set. A second @adversary pass (`ec43f6d`, `21:16:18`) added a 19th test for the sharper R-2-181/182 shape its first pass had missed — two captures of the *same* authorization with different keys, **each for the full remainder**, fired concurrently; 15 trials, exactly one `201` + one `409 authorization_not_open` every time, `(total, available)` always `(0,0)` after. Gate 2 on the served commit: 410 passed, 48 failed, zero in `test_n2_3_adversarial.py`. **Note: that second pass was redundant turn spend** — @adversary was working a queued N2-3 dispatch while N2-4A sat unstarted. HOLDS, not GO, per the ruling below. |
| N2-4 | **built, awaiting attack** | `b79a74b` | Export/import of holds and the stage-1 upgrade path: R-2-170…175. @builder closed the gap @verifier found (`snapshot.py` had **zero** references to `authorization`): `export_state()` now serialises `authorizations` + `authorization_ttl_seconds` verbatim, `validate_import_document()` defaults both when absent so a genuine stage-1 export imports clean, and `held`/`available` stay 100% derived at read time. g1 PASS, g4 PASS (`{201:667, 409:444, 200:189}`, **zero 404** — the tripwire held), g8 PASS; g2 advisory 400/447 with all 47 failures in the attributed baseline. **g5 FAIL, ruled a harness defect, not a service defect — see N2-T2.** @verifier **HOLDS** (`8eb4ee0644b4`, evidence `d6c8115`): g1 PASS, g4 PASS (`{201:678, 409:432, 200:190}`, zero 404), `collect-only` **458 ≥ 447**, scope clean but for the sanctioned finding, and all four traps independently re-confirmed by reading `snapshot.py`/`invariants.py`. **g8 FAIL — item wall clock 94.0 min > 90 cap. Planner ruling: trip accepted, item closed on content, no rework authorized** (see the governor ruling below). Dispatched to @adversary 2026-10-05 under node **N2-4A**. |
| N2-T2 | **GO — g5 PASS at the tip** | `0afe905` (refines `72bb489`, `278effd`) | Guard landed. I read the diff: probe runs **once** in `populate` (`GET /authorizations`, 200 → holds, 404 → not, with `assert status in (200, 404)` so an unexpected status is loud), recording both `_UPGRADE["holds"]` and `_UPGRADE["populated_url"]`; `snapshot` never re-probes and branches on the one stored flag; and the new-side liveness guard asserts `GET /authorizations` answers 200 on the side `populate` did **not** run against, fingerprinting nothing from it. Items 1–3 of my ruling are in. **Item 4 is not: the `body.get("held", 0)` / `body.get("available", body["balance"])` defaults at `hook.py:522` still default identically on both sides**, so a stage-2 regression that dropped those two fields from `GET /me` would compare equal here. I had accepted that as a residual gap rather than a third round trip, but **@redline closed it anyway at `0afe905`**: inside the same new-side-only guard, a second assertion requires a sampled `GET /me` body to actually *contain* `held` and `available`, so the `.get` defaults can no longer compute a safe-looking value from their absence on the new side. The defaults stay, correctly, for the old side. Both assertions now share one message prefix that names the cause. Read the diff; it is right, and N2-T2 is complete on content with no residual gap. Ratchet not in play — `hook.py` is not collected. **@verifier's g5 PASS (`a8c48245c67a`, evidence `10a49e3`, "314 earlier tests pass; upgrade from stage-1 ok") was run at `278effd`, the superseded first pass, not at `72bb489`** — my hold message crossed with the run. That PASS is real but proves only that the spurious 404 is gone; it does not exercise the guard, because `72bb489` changes the probe itself (`/me`+`held` → `GET /authorizations` 200/404) and adds the liveness assertion. **g5 re-run at `72bb489`: PASS** (@verifier `6fee5d056f2f`, evidence `764bdde`, ledger `commit:72bb4891218d`, log `evidence/gates/s2/N2-T2-g5-20261004T210734-a242.log`) — that exercises probe-once plus the `GET /authorizations` liveness assertion. **@verifier's accompanying code reading describes both assertions, but the `held`/`available` key-presence assertion does not exist in `72bb489`** — it was added at `0afe905`, so that part of the read came from the working tree, not from the commit the gate pinned. **Closed: @verifier re-ran g5 at `0afe905` — PASS** (`3e320c5d0f37`, evidence `a11d2e5`, pinned `--commit` worktree, 314 stage-1 tests, fingerprint match) and substantively confirmed the `held`/`available` presence assertion is load-bearing. It also self-corrected the earlier narrative unprompted and logged the root cause as a lesson (`19ffa99`): pin manual code reads to the named commit with `git show`/`git diff`, never a bare working-tree read. **N2-T2 is complete with gate backing at the tip — no residual gap, nothing ungated.** Folded into @verifier's next scheduled run rather than a dedicated container cycle; the stage-close `--gates all` at HEAD covers it as a backstop. @redline has asked @verifier for `--gates 5 --commit 0afe905`; either sequencing is fine, @verifier owns the box. |
| ~~N2-T2 (first pass)~~ | superseded | `278effd` | @redline's capability probe is exactly the design I specified: probe once in `populate` (`GET /me`, test for the `held` key), record the outcome, branch `snapshot` on the recorded values so both sides fingerprint the same shape; the hold-building block moved under `if supports_holds:` and the capture replay is `None`-guarded. Verified by reading the diff. **But the anti-silent-downgrade guard I required is absent**, and a second instance of the same hole exists at `hook.py:522` (`body.get("held", 0)` / `body.get("available", body["balance"])` default identically on both sides, so a stage-2 regression that dropped those fields would compare equal and pass). Returned to @redline 2026-10-05 for the guard only; no other change wanted. | Gate-5 hook is not cross-version. @builder's g5 log: `upgrade check failed: AssertionError: {"error":{"code":"not_found","message":"no such endpoint: POST /authorizations"}}` (`evidence/gates/s2/N2-4-g5-20261004T205427-c36f.log`). Confirmed against `factory/gates/g5_regression.py:22-37`: gate 5 builds the **previous** stage folder as a second container and runs `populate(old_url)` and `snapshot(old_url)` against it, then `carry`, then `snapshot(new_url)`, requiring `before == after`. `stage-2/tests/invariants/hook.py:451` calls `POST /authorizations` unconditionally and `:551` / `:560` read `GET /authorizations` and replay a capture — none of which exist on stage 1, by design (R-2-170's premise). @builder is right and could not fix it: `tests/invariants/hook.py` is @redline's boundary. **Planner ruling: hook defect. N2-4's service work stands.** @redline, 2026-10-05. |
| N2-4A | **BREACH** | attack `b6d755d` vs code `b79a74b` | @adversary, 2026-10-05. Import validation gap, exactly the risk #6 I dispatched. `validate_import_document()` in `snapshot.py` copies each imported authorization **verbatim with no per-field validation**, unlike `fixtures.validate_fixture` on the reset path; the only check that runs, `check_holds_within_balance`, sits **after** the try/except that catches per-field parsing errors, so it is unprotected. Two shapes, both confirmed: **(1) 500, not 422** — `amount` as a string → `TypeError` in `remaining_amount()`; `expires_at` deleted → `KeyError` in `is_open()`; both surface as `500 internal_error`, violating R-1-005 outright and R-1-204's required `422`. **(2) silently accepted, money created from nothing** — `captured_amount = amount + 100` and `amount = -500` both import with `204`, after which `GET /me` reports `held: -100` / `held: -500` and `available` **above** `total`. That is a conservation breach (R-2-001/002/005, R-1-207) reached through an untrusted document instead of a race. Happy path held: expiry across the boundary, partial-capture round-trip and idempotency identity all survived. Gate 2 on the served commit: 414 passed, 51 failed = the attributed 47 plus @adversary's 4 new breach tests. @adversary filed the verdict under node `N2-4`; it belongs to `N2-4A`. |
| N2-T3 | **done, awaiting a live run** | `b01b4e8` | @redline fixed it **at the source** rather than patching call sites: `ui_login_demo_user` now returns `{**u, "token": login_token(...)}` obtained after its own `reset_ok`, with a docstring naming the hazard, and all 11 call sites read `user["token"]`. I read the diff — it returns a copy, so the fixture is not mutated, and no assertion changed anywhere. **The sweep I asked for found 10 more instances of the same latent defect** (`test_ui_activity.py` ×2, `test_ui_layout.py` ×2, `test_ui_requests_split_authz.py` ×1, `test_ui_wallet_pay.py` ×5), all passing today only because nothing had exercised them loudly yet. Collection **470 ≥ 458**. Not yet exercised by a gate: @verifier's N2-5 run pins `a357441`, which predates this; it will be covered by the next gate-2 run on a later commit. | Test defect in `stage-2/tests/test_ui_auth.py:24`: `test_requests_and_authorizations_shared_html_json` reads `demo["tokens"][…]["token"]`, captured **before** `ui_login_demo_user` → `conftest.py:298` `reset_ok(fixture)` wipes `STORE.tokens`. The test asserts against a token it invalidated one line earlier. Confirmed by reading both files. @builder verified the real behaviour is correct with a live token and correctly refused to edit @redline's file. @redline, 2026-10-05. |
| N2-5B | **fixed, with @adversary and @verifier** | `5f800fc` | All three parts done. **Signup (R-1-088, R-2-185):** @builder factored the check-then-insert out of `SignupEndpoint.apply` into `routes/auth.py::create_user()`, documented as requiring `STORE.write_lock()` held by the caller; the JSON endpoint gets the lock via `Endpoint.handle()`, the UI form wraps its call in `with STORE.write_lock():`. It also dropped `_validate_signup`'s email-uniqueness pre-check — checking outside the lock *was* the race — leaving format checks there and uniqueness under the lock, which preserves R-1-088's `422 → email_taken → handle_taken` order. **Accept (R-2-187):** real parse, exact `text/html` token compared against the highest q among other listed types. **Logout (R-2-188):** unchanged, already non-revoking. All 9 adversarial tests pass; g1/g4 PASS (`{201:674, 409:436, 200:190}`, zero 404); g2 33 failed, the attributed baseline minus the two fixed breaches; g7 FAIL on error/loading only, already ruled advisory here. **g8 'FAIL' at 115.6 min is the node-tagging artifact again** — the run was tagged `--node N2-5`, a closed node; g8 on `N2-5B` PASSES. @verifier **HOLDS** (`7ac900e888d6`, evidence `310d73e`), full `--gates 1,2,4,5,7,8` on a fresh node with the box quiet: g1/g4/g8 PASS (`{201:668, 409:444, 200:188}`, zero 404), g2 441/33 matching @builder, g7 FAIL on error/loading only as ruled, `collect-only` **480 ≥ 470**, scope clean but for the sanctioned finding. It read both fixes at the pinned commit and confirmed `create_user()` is the single check-then-insert with both callers holding the lock, and `_wants_html()` does a real Accept parse. **N2-5B CLOSED.** | Fix the signup-form lock breach @adversary found, and apply R-2-185/R-2-186 structurally. **Scope widened 2026-10-05**: @adversary's deeper N2-5 pass (`d770c47`) confirmed the negotiation breach I ranked #2 in its brief — `ui._wants_html` substring-matches `"text/html" in accept`, so `Accept: application/json, text/html;q=0.01` (a client that primarily wants JSON) is served HTML, and `text/htmlx` / `application/text/html` divert although neither is the media type. Fixed under this item per **R-2-187**. @builder, after N2-4B, before N2-6′. |
| N2-4B | **CLOSED** | `22da286` | @builder added `_validate_authorization()` to `snapshot.py`, porting the reset path's per-field checks — `parse_amount` bounded 1..1_000_000_000, `captured_amount` bounded 0..amount, status enum, required `expires_at`, type checks on `payment_ids`/`closed_at`/`created_at`/`seq` — and `validate_import_document` now builds `authorizations` through it in a loop instead of the one-line verbatim copy, so records are clean typed data **before** `check_holds_within_balance` runs. All 4 of @adversary's tests pass; g1 PASS, g4 PASS (`{201:672, 409:437, 200:191}`, zero 404); g2 430/35, the same attributed baseline, nothing new. Note the deliberate divergence from the reset path: import validates `expires_at` as the **raw epoch number** this module's own export emits, not `fixtures.py`'s RFC 3339 string — correct under R-1-202, which requires import to accept this service's own export unchanged. **@builder tagged the run `--node N2-4`, not `N2-4B`, so g8 re-tripped the closed node's clock at 155.8 min — a false alarm, not a new trip; g8 on `N2-4B` PASSES.** @verifier **HOLDS** (`2b46a4020924`, evidence `de4f89f`), **recorded under the fresh node id** so g8 came back clean with nothing to escalate: g1/g4/g8 PASS (`{201:672, 409:438, 200:190}`, zero 404), `collect-only` 470, scope clean but for the sanctioned finding, and it read `_validate_authorization()` at the **pinned** commit confirming every check runs before `check_holds_within_balance`. Gate 2 untagged 430/35, matching @builder exactly, all 4 adversarial tests green. **Import-validation breach closed.** @adversary re-verified at `22da286`: **HOLDS**, 438 passed / 36 failed, all four breach tests green, zero regressions; the 36 are the 3 open N2-5 breaches plus the attributed baseline. Note the re-verification pinned `22da286`, the first fix — **the seven-collection audit at `2c3544f` has not been attacked**, only gated. Dispatched to @adversary as the over-strictness pass. @verifier then verified `2c3544f` too (**HOLDS**, `0f4b31950657`, evidence `7c6eb7a`): g1/g4/g8 PASS, g2 436/34 matching @builder, and it confirmed the atomicity ordering by reading `routes/test_control.py` — `ImportEndpoint.validate_fields` (including idempotency validation) runs **before** `apply()`/`STORE.apply_import`, so a malformed record is rejected before any collection swaps in. That is the half-replaced-destination risk genuinely closed, not just asserted. It also independently reproduced the signup race (10/10 succeeded) and read `_handle_signup` directly. **Still missing: gate 5.** | Fix the import-validation gap @adversary breached. @builder, 2026-10-05, **sequenced after N2-5** — see the sequencing ruling below. |
| N2-5 | **built, with @adversary and @verifier** | `a357441` (bulk at `6bd6d8d`) | Browser shell. All six routes; R-2-091 negotiation diverting only on `"text/html" in Accept` for GET, with everything else falling through untouched; session is one HttpOnly cookie holding the same bearer token, and `auth.py` never reads cookies, so R-1-089 is intact; `current-handle` is a sibling element with no `@`; `auth-error` omitted from the DOM rather than hidden; one CSS system and one JS module (`parseAmountToMinorUnits`/`formatAmount`, parsed in integer space) for N2-6…N2-9. g1 PASS, g4 PASS (`{201:672, 409:441, 200:187}`, zero 404), g8 PASS. **g2 423/35, every failure named**: 1 pre-existing, 1 test bug (see N2-T3), 33 content this item does not build. **g7 FAIL — ruled advisory for this item only; see the gate-7 ruling below.** @verifier **HOLDS** (`39eb76cf8b68`, evidence `f69aaa2`): re-ran tagged with `--commit`, g1/g4/g8 PASS (`{201:670, 409:443, 200:187}`, zero 404), `collect-only` 470, scope clean but for the sanctioned finding, g2 423/35 matching exactly. It confirmed the test bug **by reading the pinned commit** rather than the working tree — applying its own `19ffa99` lesson — and matched it to the junit's `302 Found` login-wall redirect. On g7 it reviewed all 18 screenshots (6 routes × 3 viewports) and confirmed the two missing markers are a genuine scope gap, not evasion: **gate 7's automated checks all passed** — no overflow at 375/768/1280, contrast fine, touch targets fine, consistent design tokens, visible labels, clean empty-state copy. | UI shell and design system: R-2-090…093, R-2-100…111, R-2-120…125. @builder, 2026-10-05. This is the critical path: gate 2 stays red for every item until screens exist, so the ~48 outstanding failures cannot clear before N2-5…N2-9 land. |
| N2-6 | planned | — | — |
| N2-7 | planned | — | — |
| N2-8 | planned | — | — |
| N2-9 | planned | — | — |
| N2-10 | planned | — | — |

States: planned → dispatched → built → attacked → GO | NEEDS_WORK | blocked.

Stage: open.

## Gate 2 is advisory per item until the UI lands (planner ruling, 2026-10-04)

@redline's N2-T suite contains ~11 UI files driven by Playwright against screens that do not
exist until N2-5 … N2-8. Gate 2 fails when **any** test fails, so **no item from N2-1 to N2-4
can make gate 2 green**, however correct it is. Left unruled, that would burn @builder's four
attempts against an impossible gate and trip the governor on work that is not defective.

**Ruling, and it is the same shape as stage 1's `g2 advisory 73/126` on N1-2/N1-3:**

1. **Per item, gate 2 is advisory.** The binding per-item measures are:
   - **no regression** — every test green at stage-1 close (`4cce19d`, 314 tests) is still green;
   - **item-scoped green** — the tests covering this item's own requirement ids pass.
2. **Gate 2 is binding at stage close**, on the full suite, with zero failures, zero errors and
   zero skips. A UI test still red at close is a close failure, not an advisory note.
3. The test-count ratchet is unaffected and still binding: 431 ≥ 314.
4. @verifier states, in every per-item verdict from here, which of the two binding measures it
   checked and the number it saw. "Gate 2 red, advisory" on its own is not a verdict.

This is a scheduling fact about tests-before-code, not a softened check: the same 431 tests
have to be green at close, and **nothing here lowers that bar.** It is recorded before
@builder's first result lands rather than after, so it cannot be mistaken for an accommodation
made to rescue a red number.

## N2-1 pulled R-2-012/013/017 forward from N2-2 (planner, accepted)

@builder's N2-1 also switched the funds checks in `payments.py`, `requests.py` and
`settlements.py` from `total` to `available` (R-2-012, R-2-013, R-2-017), which `plan/s2-dag.md`
assigns to N2-2. **Accepted and the DAG is amended rather than the work reverted:** the holds
model is inert without them — R-2-002 says held funds cannot fund new payments, so a `held`
that nothing consults proves nothing, and the storm could not exercise R-2-002 at all. Same
disposition as stage 1's N1-2, which pulled `GET /requests` filters forward from N1-6.
**N2-2's requirement list therefore drops to R-2-014/015/016/018 plus R-2-040 … R-2-046 and
R-2-080 … R-2-084.** Recorded so the DAG stays an honest description of what was built where.

## N2-T verified by the planner, not taken on report (2026-10-04)

@redline's READY at `36bcb2d` claims 123 distinct R-2 ids covered and both carried-in fixes
landed. Checked rather than accepted:

| claim | check | result |
|---|---|---|
| every R-2 id covered | distinct ids in `stage-2/tests/` vs in `plan/s2-requirements.md` | **123 = 123**, no gap |
| `_send_raw` reads `Content-Length` | `grep -n 'content-length' stage-2/tests/test_http_framing.py` | present at line 54, with the docstring at 21 |
| the `sed` corruption was really reverted | `grep -rn 'data-tid' stage-2/tests/` | **no hits** — clean |
| gate 7 hook complete (G7-1) | `hook.missing(m,'setup','operation','invariant')` | `[]`; `ui_login` callable; `transient`, `populate`, `snapshot`, `carry` all present |
| `UI_ROUTES` covers the six routes | read of `hook.py:592` | all six, in order |
| edit boundary | `factory.scope 4cce19d..36bcb2d` | **every commit is inside its seat's scope** |
| nothing deleted | diffstat: 15 files, 2500 insertions, 22 deletions | deletions are the `_send_raw` rewrite only |

**Two self-catches worth recording**, because both are the class of defect that passes every
gate while making tests meaningless:

1. A `testid()` helper collided with pytest's discovery pattern and was being collected as a
   bogus test item. @redline renamed it to `tid()` — and the blind `sed` that did the rename
   also corrupted three literal `"data-testid"` DOM-attribute strings into `"data-tid"`, which
   would have **silently broken every UI selector** while the suite still "ran". Caught by grep
   before committing. Verified reverted above.
2. It found and closed three of its own coverage gaps (R-2-062, R-2-063, R-2-156) before
   reporting, rather than reporting 120 ids and calling it complete.

**One limitation, honestly stated by @redline and accepted:** no storm status-mix dry run this
turn, because no stage-2 service exists yet. Stage 1's first storm logged `{404: 1300}` and
conserved money trivially, so a mix is only meaningful once N2-1 serves something. **The mix
must be reported with the first gate 4 run that has a live service** — I am carrying that as an
obligation on N2-1's verification, not letting it lapse.

## N2-1 verification: the storm-mix obligation is discharged (2026-10-04)

The obligation I carried onto N2-1 — report the gate 4 status mix once a live service exists —
is met. @verifier's tagged g4 run logged `{404: 149, 201: 600, 409: 300, 405: 79, 200: 172}`,
close to @builder's own figures. Read against stage 1's first storm (`{404: 1300}`, which
conserved money trivially because nothing moved), this mix is **load-bearing**: 600 creations,
300 refusals and 172 replays means R-2-002 and R-1-001 were actually exercised.

**One number in it is a pre-condition, not a defect, and must disappear:** the `405: 79` is the
hook calling `/authorizations` and `/authorizations/{id}/capture`, which do not exist until N2-2
and N2-3. **If any `405` survives in the gate 4 mix after N2-3 closes, that is a defect** — it
means a write path the hook storms is unrouted. Carried as an obligation on N2-3's verification.

## Two findings on N2-1's verification, and how they are ruled (planner, 2026-10-05)

@verifier reported both of these against its own interest rather than rounding them off, which
is the behaviour I want and the reason I can close on its report.

**1. Gate 2's `"a test was removed"` message is a false signal here. Do not act on it.**
The full `--gates 2` run hit the tool's **900 s timeout** at ~83%, so `junit.xml` was never
written and the wrapper's fallback mis-reported a missing file as a deleted test. The cause is
@redline's ~11 Playwright files retrying against screens that do not exist until N2-5. The
ratchet itself is intact and was measured the right way: `--collect-only` collects **447**
tests against stage 2's 431 and stage 1's 314.

**Ruling.** Until gate 7 has real screens to visit, the binding ratchet measure is the
`--collect-only` count, not gate 2's removal message. **This does not relax the ratchet** — 447
≥ 431 ≥ 314 is checked every item, by a method that actually measures it. Two consequences I am
recording now so they cannot be discovered at close: the same 900 s timeout will hit the
**stage-close** gate 2 run, where gate 2 is binding and a timeout is not a pass; and under
G7-4 an empty record is a close failure. So **at close, gate 2 must produce a written
`junit.xml`** — if the full suite cannot finish inside the tool's timeout, @verifier reports
that as a BLOCK on the close run, and I re-plan the close rather than accept a truncated run.

**2. The 336/49 item-scoped split is corroborated, not independently re-derived. Accepted.**
@verifier could not reproduce @builder's split directly: serving a container via
`factory.gates.serve` and then invoking `pytest` against it was refused by the sandbox's own
permission policy. It fell back to the dot/F sequence of the timed-out run: **325 passed / 67
failed of the 392 seen before cutoff**, with the same *clustered* shape @builder described —
whole files failing on N2-2/N2-3-dependent calls, not failures scattered through passing files.

**Ruling: this is enough to close N2-1, and the gap is closed by N2-2 rather than argued about.**
The cluster shape is the load-bearing part of the claim — scattered failures would mean the
holds model broke working behaviour, clusters mean tests are red for the one legitimate reason
(their endpoints do not exist yet). The three gates that *are* fully independent (g1, g4, g8)
all pass, and g4 is the one that would catch a real holds defect. So I accept the corroboration
and take @verifier's own recommendation: **the 49 files are the spot-check for N2-2.** They
cover R-2-040…046 and R-2-080…084, so if the attribution was honest they flip green when N2-2
lands, and if it was not, they do not. That turns a gap in evidence into a prediction N2-2 must
satisfy — recorded as an obligation on N2-2's verification, with the number to beat written
down in advance: **at N2-2, the item-scoped set is green and the collected count is ≥ 447.**

## `factory.record` will not accept a GO for N2-1 … N2-4, and that is correct (planner, 2026-10-05)

@verifier agreed both rulings above, tried to issue the GO exactly as specified, and was
refused by the tool:

```
refusing GO: gate g2 has no result for this item at this commit. Record NEEDS_WORK instead.
```

**I read the code rather than ruling from the message, and @verifier's diagnosis is exactly
right.** `factory/gates/common.py:224` defines `run_pytest(..., timeout: float = 900, ...)` as a
**default parameter with no CLI flag**, and `g2_spec_tests.check` calls it with that default. On
timeout the subprocess dies before pytest writes `--junitxml`, so `pytest_counts(junit)` returns
`tests: 0`, which trips `counts["tests"] < high` — the line that prints *"a test was removed"*.
The message is a **missing file reported as a deletion**. There is no knob to raise the timeout
and `factory/` is not mine to edit.

**Ruling: option 1. N2-1 terminates on HOLDS, and I am not papering over what that means.**

1. **`factory.record` refusing a GO the gates do not back is a feature, and I will not route
   around it.** It is the property that makes a verdict an exit code instead of an opinion
   (`FACTORY.md`: *"factory.record refuses a GO the gate results do not back"*). An item that
   cannot make gate 2 green has not earned a GO, and the tool is right to say so.
2. **I rejected option 2.** Re-running gate 2 tagged `--node N2-1` would predictably time out
   again — tagging does not make it faster — and would write a **red g2 result against N2-1**
   plus an attempt against the governor, manufacturing a misleading record to satisfy a
   bookkeeping requirement. Burning an attempt to log a failure we have already explained is
   worse than having no record.
3. **N2-1 … N2-4 terminate on HOLDS**, with the two binding measures from the G2-advisory
   ruling stated in the verdict. **HOLDS is not a GO and must never be reported as one.** The
   stage-2 result in the final report says so in those words.
4. **The first item that can make the full suite green — N2-5 onward — must record a tagged g2
   result and earn a real GO.** The gate-backed chain resumes there; it does not stay suspended.
5. **The stage-close GO must be fully gate-backed, gate 2 included.** That is unchanged and is
   where the deferred rigour is actually collected.

### The close-run timeout risk is retired — measured, then fixed in the tooling

**Measured (@verifier, from stage 1's close `junit.xml`, no new container needed):** the
314-test non-UI baseline runs in **179.8 s** — 20% of the old 900 s budget — and summed per-test
durations agree at 179.46 s. **Two tests account for 135 s of the 180 s**: N1-10.2's parked-waiter
adversarial pair (`test_import_landing_while_waiters_are_parked_on_an_in_flight_claim` 68.02 s,
`test_reset_landing_while_waiters_are_parked_on_an_in_flight_claim` 66.90 s). Everything else in
the 314 is fast; third place is 5.87 s. So the non-UI baseline was never the risk — the
Playwright files were, exactly as predicted, and they are the part N2-5 … N2-8 will make fast.

**Then the tooling was fixed.** `factory/gates/common.py` and `factory/gates/g2_spec_tests.py`
now carry a `--timeout` flag (default **2400 s**, was a hard-coded 900 s) and a `timed_out`
count, and gate 2 reports a timeout as *"the suite did not finish within Ns (raise --timeout);
**no test was removed**"*. **I reviewed this as a possible gate weakening and it is not one:**

- a timeout still calls `gate.finish(False, …)` — it **FAILS**, it does not pass;
- `green(counts)` is untouched, so gate 2's pass condition is unchanged;
- the only thing that changed is that a missing `junit.xml` is no longer **misattributed** to a
  deleted test. The gate became more truthful, not more permissive.

**It does not change the HOLDS ruling, and it is worth being precise about why.** The GO was
refused because gate 2 has **no green result** for N2-1, not because the run timed out. With the
longer timeout a tagged run would now *complete* — and complete **red**, because the UI tests
legitimately fail until screens exist. So N2-1 … N2-4 still cannot earn a GO, points 1–5 above
stand unchanged, and option 2 is still the wrong trade: it would now buy a legible FAIL against
N2-1 plus a governor attempt, instead of a timeout against N2-1 plus a governor attempt.

**Condition satisfied (2026-10-05).** It is committed at **`be37a18`**, authored
`Human <human@band.local>`, factory code only, the same two files reviewed above, and
`git status -- factory/` is clean. @verifier confirmed it was not its edit and I verified the
commit myself rather than taking the report. **The close run is auditable.** The paragraph below
records why that mattered.

**The condition, for the record.** The change was initially **uncommitted in the working tree**. A stage-close GO produced by uncommitted gate code is **not auditable** —
`--commit <sha>` checks the stage folder out into a private worktree, but the gate scripts
themselves run from the working tree, so the close run's behaviour would not be reproducible
from anything in history and `factory.ledger`'s hash chain would attest a result no commit can
explain. **Whoever made the edit must commit it as a factory-only maintenance commit before the
close run**, with the precedent already set by `01e3a7f` ("Factory maintenance during the run …
scope check treats factory-only commits as maintenance. Factory code only."). I did not commit
it myself: `factory/` is not mine to edit, and committing another seat's work under my author
line is exactly what the scope check exists to catch.

### Forward tripwire on gate 2 runtime, because stage 4 is the one at risk

180 s of 2400 s at stage 1 is comfortable. The trajectory is what to watch: each stage copies
its predecessors' tests forward and adds more, the parked-waiter pair's 135 s is a fixed cost
in every stage, and stages 3 and 4 are where the dispatch asks for the most test effort.
**At every stage close from here, @verifier reports gate 2's total wall time.** If it exceeds
**1600 s** (two thirds of the budget), I re-plan the close for the following stage before
reaching it rather than at it. Recorded now so stage 4 cannot be surprised by it.

## The `405` tripwire fired correctly, and reading *why* found a better one (planner, 2026-10-05)

N2-2's gate 4 mix is `{404: 149, 201: 638, 409: 338, 200: 175}` against N2-1's
`{404: 149, 201: 600, 409: 300, 405: 79, 200: 172}`. The obligation I put on N2-3 — that no
`405` survive — is **discharged one item early**, and the arithmetic is exact rather than
approximate: `+38` on `201`, `+38` on `409`, `+3` on `200` is **+79**, precisely the 79 `405`s
that disappeared. Those were the `_auth_create_op` slice (`i % 13`, ≈77 of 1000 ops), which now
routes. Nothing else in the mix moved.

**But `404` is identical at 149 in both runs, and that is the number worth reading.** I traced
it rather than accepting a clean-looking mix. `stage-2/tests/invariants/hook.py` dispatches
`_auth_void_op` at `i % 19` and `_auth_capture_op` at `i % 17` — about 112 calls per storm —
and capture and void have no routes until N2-3, so those calls are real HTTP `404`s sitting
inside that 149. @verifier confirmed independently that no capture/void route files exist.

**Sharpened tripwire for N2-3, replacing the spent `405` one.** After N2-3 lands, those ~112
calls must return real capture/void statuses, so **the `404` count must fall materially from
149** — expect roughly 40 or below, not 149. **If `404` stays near 149 after N2-3, capture and
void are not being reached**, whatever the item's own tests say. This is a stronger check than
the `405` one because it cannot be satisfied by a route merely existing; it only moves if the
storm actually transacts against it.

### A latent fragility in gate 4, recorded before it can bite

`_auth_capture_op` and `_auth_void_op` both open with:

```python
targets = ctx["seed_auth_targets"]
if not targets:
    return 404
```

That is a **synthetic `404` returned without making any HTTP call at all**, and it is
indistinguishable in the mix from the real `404` that an unrouted capture returns today. So if
`seed_auth_targets` were ever empty, the capture and void slices would silently become no-ops,
the mix would still show a healthy-looking band of `404`s, and **gate 4 would stop testing
money conservation on the capture path — the single most dangerous operation in stage 2, being
the only one that spends held money — while reporting nothing wrong.**

What stands between us and that today is three lines of fixture: `stage-2/tests/demo_fixture.py`
seeds exactly **3** authorizations with `status: "open"` (two far-future, one deliberately
long-past to exercise R-2-030's expiry path). I checked; they are there, so the slices are live.
Recorded because the failure mode is silent, and because a fixture edit in stage 3 or 4 — where
these same hooks copy forward — could remove it without any gate going red. **The `404`-drop
tripwire above is also the guard for this:** it is the one observable that distinguishes "the
capture slice ran" from "the capture slice was skipped".

### The `404`-drop tripwire fired clean, and it changed the fragility it was guarding

N2-3's mix is `{201: 672, 409: 438, 200: 190}` — **zero `404`**, against 149 at N2-1 and N2-2.
I predicted "≈40 or below"; the actual is zero, because every call the hook makes now hits a
routed endpoint. So the ~112 capture and void calls per storm are genuinely transacting, which
is the thing the mix could not previously tell us. **Both tripwires I set on this item have now
fired correctly and are spent** (`405` at N2-2, `404` at N2-3).

**A useful side effect, which is why the number was worth chasing rather than just the pass.**
The latent fragility recorded above — `_auth_capture_op` and `_auth_void_op` returning a
**synthetic `404` with no HTTP call** when `seed_auth_targets` is empty — was dangerous
precisely because it hid inside a band of 149 legitimate `404`s. With the real `404`s gone,
**zero is now the baseline, so any `404` reappearing in the mix is a signal rather than noise.**
The silent failure mode became self-announcing without anyone editing a hook. Carried forward:
**a nonzero `404` count in any stage-2, 3 or 4 storm is worth tracing before accepting the run** —
it most likely means a capture/void slice went vacuous, not that the service regressed.

### The three capture/void traps, independently confirmed

@verifier read the implementation rather than trusting the tests, and all three resolved:

- **R-2-066** — `apply()` debits and credits `STORE.wallets` directly and never goes through
  `available_for()`, so a capture spends the hold rather than the payer's spendable balance.
- **R-2-005** — there is **no explicit release path at all**, and that is correct rather than a
  gap: `held_for()` filters on `is_open(a, now)` and `effective_status()` returns the stored
  status once it is `captured`/`voided` (`holds.py:20-27`), so a closed authorization drops out
  of `held_for()` by construction. **There is nothing to double-release.** This is the stronger
  design — the invariant holds structurally instead of depending on every release path being
  written correctly once.
- **R-2-065 vs R-2-073** — capture branches `expired` against `not-open` explicitly; void
  collapses both to `not-open` unconditionally. A deliberate per-endpoint asymmetry that the
  spec requires, not an inconsistency.

## The first complete gate-2 picture for stage 2, and it closes the runtime question (2026-10-05)

@adversary ran gate 2 with the new 2400 s budget at `f2beb86` and **the suite completed** —
no timeout, a written `junit.xml`, a legible result:

```
399 passed, 48 failed, 0 errors, 0 skipped      (~200 s wall)
```

Three things follow, and together they retire two open worries.

**1. The runtime risk is gone, measured directly rather than predicted.** The full 447-test
suite runs in **~200 s against a 2400 s budget** — 8% of it. I no longer need stage 1's
durations as a proxy, so **the obligation I placed on the N2-5 verification is discharged
here instead.** The 1600 s forward tripwire stays, because stages 3 and 4 still add tests.

**2. `399 + 48 = 447` exactly**, matching the `--collect-only` count. Nothing is being silently
skipped or lost, so the ratchet and the pass/fail split describe the same suite.

**3. Every single failure maps to a dispatched or planned item. No orphans.** This is the
accounting I need to believe stage 2 can close:

| failures | cause | closed by |
|---|---|---|
| 47 UI tests (wallet_pay ×14, layout ×11, requests_split_authz ×8, auth ×8, activity ×5) | the screens do not exist yet | N2-5 … N2-8 |
| 1 `test_upgrade_stage2.py` | authorizations are not in `snapshot.py` | **N2-4, in flight** |
| 0 in `tests/adversarial/` | @adversary's own test bug, fixed at `f2beb86` | done |

So the distance to a green, binding gate 2 at close is exactly: **N2-4 plus the four UI items.**
Nothing else is red, and no failure is unexplained.

## N2-3 was never attacked — the handoff did not happen (planner, 2026-10-05)

Checked the ledger rather than assuming the chain completed. **`N2-3` holds exactly one
`verdict` event, from @verifier. There is no @adversary verdict for it.** @verifier's report
quoted a HOLDS id for N2-3, but that was its own record; the same pattern as N2-1, where
@adversary found zero adversary events and recorded its own.

**This is a real gap, not bookkeeping.** N2-3 is capture and void — the only code in stage 2
that spends held money, and the place R-2-005 double-release and R-2-066 live. @verifier
confirmed all three traps by **reading the implementation**, which is worth having and is not
an attack: nothing hammered the races. @adversary has been waiting to be handed N2-3 and
nobody handed it over, because @builder went straight from N2-3's commit to my dispatch of
N2-4. **Dispatching the attack now, against `07052a8`, in parallel with N2-4's build.**

Process note for the remaining items: **an item is not done when @verifier gates it — it needs
the attack too.** The N2-1 and N2-3 near-misses were both visible in the ledger as a missing
adversary verdict, so the check is cheap: `grep '"node":"<id>"' evidence/ledger.jsonl | grep
'"seat":"adversary"'`. I will run it before closing each remaining item.

## Governor ruling: N2-4's g8 trip is accepted, not reworked (planner, 2026-10-05)

@verifier reported N2-4 **HOLDS** on content with **g8 FAIL — `item N2-4: minutes 94.0 > cap 90`**.
I re-ran the governor myself and confirm the number; it is still climbing, because the clock runs
from first dispatch and the node is still live.

**Ruling: the trip is accepted and N2-4 is closed on content. No rework is authorized.** A wall-clock
cap exists to stop further iteration on an item, not to retroactively invalidate work that is already
finished and independently confirmed. N2-4's content has @builder's four traps, @verifier's
independent re-read of `snapshot.py`/`invariants.py`, g1/g4 PASS and a satisfied ratchet behind it.
Reopening it would spend more of exactly the budget the cap is protecting.

**Part of the overrun is mine.** I dispatched the follow-up attack under the *same* node id,
`N2-4`, at 20:50 — roughly 83 minutes after the original dispatch — so the finished item's clock
kept running through a fresh pass. The governor was measuring one node across two passes of work.
Recorded as a planner lesson in `plan/lessons.md`.

**Correction applied:** the in-flight attack is re-keyed to node **N2-4A** and carries its own
budget. I am not interrupting @adversary mid-attack to tell it so; I will translate its verdict to
`N2-4A` when it reports. If it returns a BREACH, the fix becomes **N2-4B**, a new item with a fresh
cap, ranked against the remaining stage-2 work — it does not reopen N2-4.

Stage budget is not at risk: stage 2 spend is **$9.33 of the $120 cap**.

## Carried into N2-T from stage 1, not a new requirement

`stage-1/tests/test_http_framing.py`'s `_send_raw` helper decides a response is complete when
it sees `\r\n\r\n` anywhere in the accumulated bytes, rather than reading the declared
`Content-Length`. That heuristic is wrong in general — any response whose body crosses a
segment boundary defeats it — and it is only adequate today because the framing tests assert
on small error envelopes and the server now coalesces its writes. The file copies into stages
2, 3 and 4, so **@redline fixes the helper as part of N2-T, every assertion byte-identical.**
Recorded rather than fixed during stage 1 because it was latent, not active.

## Four gate-7 rules for stage 2 (planner, carried from `plan/s2-dag.md`)

Gate 7 never ran at stage 1 — correctly, there being no browser product, and by my own
instruction to omit `UI_ROUTES`. It is load-bearing now, and a gate that records nothing is
indistinguishable from one that passed. Hence:

- **G7-1** @redline's stage-2 hook must define `UI_ROUTES` covering `/`, `/requests`,
  `/split`, `/signup`, `/login`, `/authorizations`, and `ui_login(page, base_url)`.
- **G7-2** Every item from N2-5 onward runs `--gates 1,2,4,7,8`, not `1,2,4,8`.
- **G7-3** @verifier quotes gate 7's `RESULT:` line, with viewport and violation counts, in
  every verdict on a UI item.
- **G7-4** **A missing or empty gate 7 record at stage-2 close is a close failure, not a
  pass.** The same rule as "a traceback is not a verdict": absence of measurement is never
  evidence of success.

### Gate 7 is proven to work before it is load-bearing (@verifier dry run, 2026-10-04)

@verifier ran `factory.gates.run stage-2 --node N2-0-dryrun-g7 --gates 7` against the
copied-forward stage 2, which has no UI yet, and got:

```
g7: FAIL — TimeoutError: Page.fill: Timeout 30000ms exceeded.
```

It diagnosed the cause rather than reporting the traceback: @redline's in-flight `hook.py`
already defines `UI_ROUTES` and `ui_login` per G7-1, so gate 7 tried to sign in before
visiting the routes and timed out filling a form that does not exist yet. Nothing to fix —
that is the expected state until N2-5 lands a real screen.

**This closes the question I asked and it strengthens G7-4.** Gate 7 can express a verdict in
this repository: it produces a **legible FAIL**, not a silent skip and not an empty record. So
at stage-2 close, an absent or empty gate 7 record can no longer be explained away as "gate 7
cannot run here" — we now know it can, and we know what its failure looks like. The only
remaining explanations for an empty record are that it was never run or that its output was
lost, and both are close failures under G7-4. Worth the one quiet run to establish, and taken
by @verifier on a turn when nothing else needed it.

## Sequencing ruling: N2-4B waits for N2-5 (planner, 2026-10-05)

@adversary's N2-4A BREACH is real and must be fixed before stage close. It does **not** preempt
N2-5, and I am not asking @builder to drop a half-built UI for it.

Reasons, in order. The defect is reachable only through `POST /_test/import` with a hand-crafted
document — no ordinary API traffic can produce it, so nothing @builder writes for N2-5 can be
built on top of a corrupted state. N2-5 is the critical path: gate 2 and gate 7 cannot go green
for **any** stage-2 item until screens exist, and every item behind it is already waiting. The fix
itself is small and fully specified — port `fixtures.validate_fixture`'s authorization loop into
`validate_import_document` so type and range checks run **before** `check_holds_within_balance` —
so it loses nothing by being done second. And a context switch out of and back into a large UI
build costs more than the fix takes.

Against that: the breach violates R-1-005 and conservation, and `POST /_test/import` is an
unauthenticated endpoint the public checks exercise under R-1-204, so gate 3 at stage close would
very likely catch it. That makes it a hard blocker for closing stage 2 — it is not a hard blocker
for continuing to build it.

**N2-4B is therefore the first item after N2-5 hands off, ahead of N2-6.** It does not reopen
N2-4; it is a new node with its own cap.

## Gate-7 ruling: advisory for N2-5, binding from N2-6 (planner, 2026-10-05)

Gate 7 failed N2-5 with `no data-state marker for: error, loading`. @builder declined to add inert
template markup to satisfy the string scan and asked instead. That was the right call: fabricating
a marker for a state the product cannot enter is gaming the gate, and I would have returned it.

**Ruled advisory for N2-5 and binding from N2-6 on.** R-2-109 attaches the empty, loading and error
states to the balance, the activity feed, the request lists and the authorization list — none of
which N2-5 builds. N2-5's scope is chrome, routing, the design system and the auth screens, and the
only error path in it (`auth-error` on a failed login) is by construction never reached by gate 7's
walk, which logs in successfully via `ui_login`. There is no honest way for this item to show a
loading state: nothing in it performs a fetch.

**It closes for real at N2-6, not later.** `factory/gates/g7_ui.py:35-44` scans not only the walked
HTML but the contents of every same-origin `<script src=…>`, matching `data-state="…"` **and**
`dataset.state = "…"`. So when N2-6 adds the first real fetch with genuine
`dataset.state = 'loading'` / `'error'` transitions in `app.js`, gate 7 sees them because the code
actually exists and runs — no marker needs to be faked. N2-6 is therefore the item where gate 7
must go green, and I will not grant a second advisory pass on it.

## N2-5 BREACH and a standing rule: the browser must not reimplement a write path (planner, 2026-10-05)

@adversary found that `service/ui/pages.py::_handle_signup` duplicates `routes/auth.py`'s
`SignupEndpoint` — check email, derive handle, check handle, insert — but runs it **directly
against `STORE` with no `write_lock()`**. Ten concurrent form signups with one identical email
all returned `302` and created ten user records sharing that email and derived handle, several
unreachable afterwards because the lookup maps were overwritten by the last writer: zombie
accounts holding live session tokens that nobody can log back into. `SignupEndpoint`'s own
comment states the JSON path holds exactly one `201` and one `409` under that race (R-1-088).
The form path lost that guarantee by copying the logic instead of calling it.

The rest of the item held, including the two I was most worried about: the session cookie never
authenticates a plain JSON endpoint (R-1-089), and `display_name` containing `<script>` renders
escaped.

**This is a class, not an instance.** N2-5 is the first item with a browser write path, and
N2-6…N2-9 add six more — pay, request, authorize, capture, void, split. Every one duplicated is
another chance for lock discipline, validation order, error precedence or idempotency to drift
from the JSON path that the whole stage-1 test suite protects. Signup is simply the one that
happened to exist when @adversary went looking.

So this is recorded as **R-2-185 and R-2-186**, binding for the rest of stage 2 and carried into
stages 3 and 4: a UI handler may translate form encoding to the endpoint's request shape and
translate the response to a redirect or a rendered error, and may not touch the store directly.
The fix for N2-5B is therefore structural — route the form through `SignupEndpoint` — not a
`write_lock()` added to the duplicate.

## Re-plan: stage 2's remaining items compressed from six to two (planner, 2026-10-05)

Measured from the ledger, not estimated: stage 2's first event was `17:06:11`, its latest
`22:16:09` — **310 minutes elapsed of the 480-minute stage cap, 170 remaining.** Spend is fine
($15.69 of $120); wall clock is the binding constraint. The original plan has six items left
(N2-5B, N2-6, N2-7, N2-8, N2-9, N2-10) plus the stage-close gate run. N2-5 alone took ~70
minutes of build time. Six items will not fit in 170 minutes, and I would rather compress
deliberately now than have the governor trip mid-item and descope by accident.

**N2-6 and N2-9 merge into N2-6'.** `pay-uncertain`, same-key retry and latest-refresh-wins are
not separate features — they are properties of the single client-side fetch layer the pay form
introduces. Building them as two items means writing that layer, handing it off, and then
reopening the same file. One item, one attack, one verification.

**N2-7 and N2-8 merge into N2-7'.** `/requests`, `/split` and `/authorizations` are three
list-render-plus-action screens sharing one set of patterns, all of them downstream of the fetch
layer N2-6' establishes. The only reason they were separate was dependency ordering that no
longer binds once N2-6' lands.

**N2-10 folds into stage close.** Gate 4 already storms every item, and @adversary has attacked
every item individually; a separate hardening pass largely re-runs what the per-item gates and
attacks have already done. The stage-close `--gates all` run is the real hardening check.

This is a compression of *sequencing*, not of scope: every R-2-* requirement still has an owner
and nothing is being dropped. If the cap trips anyway, N2-7' is the item to land partially —
`/requests` first, since it is the one route the API shares and the one with existing tests.

## Two rulings from @adversary's deeper N2-5 pass (planner, 2026-10-05)

**The Accept breach is real and folds into N2-5B** rather than opening a new node: @builder is
already inside the UI layer for the signup fix, and with 170 stage-minutes left a separate
build-attack-verify cycle for a one-function change is not affordable. Recorded as **R-2-187**,
which fixes the exact semantics rather than leaving @builder to guess at q-value handling.

**Logout does not revoke a token (R-2-188).** @adversary reported this as a clarification, not a
finding, which was the right call — R-1-090's literal text only promises that a new login does
not invalidate an earlier token. Ruling on the most literal reading that satisfies everything
else: logout clears the cookie and revokes nothing. R-1-090 says tokens never expire, no endpoint
in any stage is granted revocation, and R-1-205 requires export/import to preserve existing
tokens. Since the browser session carries the same kind of bearer token the API issues, a
revoking logout would break a concurrently running API client — the opposite of what R-1-090
protects.

**A negative result worth recording:** @adversary extracted `parseAmountToMinorUnits` from
`app.js` and ran all 24 brief cases directly under Node — `1e3`, `.5`, `5.`, signs, whitespace,
commas, `Infinity`, `NaN`, empty, full-width digits, overflow-length digit strings, and the
`minor_units: 0` `"15.0"` case — and every one matches spec. It explicitly declined to file a
finding. The decimal parser is the single most reused piece of N2-6′ and N2-7′, so knowing it is
sound before five more forms are built on it is worth as much as a breach.

## The N2-4B audit found more than the breach did (planner, 2026-10-05)

@builder answered the widening question at `2c3544f`, and **every other collection in
`validate_import_document` had the same verbatim-copy gap authorizations did.** Two were live
crashes waiting on a delay, which is why asking was worth the turn:

- **`password_hash` as a non-string** sails past `verify_password`'s `except ValueError` — that
  catches a malformed *string* hash — into an uncaught `AttributeError` on `.split("$")`. A `500`
  on the **next login**, long after the import that planted it returned `204`.
- **A non-numeric `requests.amount`** reaches `PayRequestEndpoint.apply`'s arithmetic uncaught,
  the moment anyone pays that request post-import.

The most important one is structural: **idempotency records were never validated at all**, and
`IDEMPOTENCY.restore()` runs inside `Store.apply_import` *after* every other collection is
already swapped into the live store, indexing every field with no `.get()`. A malformed record
would have crashed there and left the destination **half-replaced** — precisely the failure I
called out in the N2-4B brief as worse than the bug being fixed. It is now validated structurally
before `apply()` runs, so any rejection leaves the swap atomic.

@builder verified by crafting the three malformed documents itself and comparing `GET /_test/export`
byte-for-byte before and after each rejection, rather than inferring from the suite.

**Gap in the evidence:** that run was `--gates 1,2,4,8`. The new validation is strictly stricter
than what came before, and R-2-170 requires a genuine **stage-1** export to keep importing clean.
Stage-1's `export_state` emits the same keys (`users`, `wallets`, `payments`, `requests`,
`settlements`, `tokens`, `idempotency`, `next_seq`), so it should pass — but "should" is what gate
5 exists to settle. @verifier asked to add `--gates 5`.

## Standing instruction: gate 5 rides along until it passes at or after `2c3544f` (planner, 2026-10-05)

Gate 5 has not run on any commit containing @builder's seven-collection import audit. The
tightened validator is precisely what could reject a genuine **stage-1** export, which R-2-170
requires to import clean, and no other gate exercises a real stage-1 binary as the upgrade
source. I asked for `--gates 1,2,4,5,8` on N2-4B; the run came back `1,2,4,8` plus an untagged
g2.

Rather than spend a dedicated container cycle while @builder is building N2-5B and @adversary is
serving commits for the over-strictness attack, **every remaining verification run in stage 2
includes gate 5 until it has passed once on a commit at or after `2c3544f`.** The next one is
N2-5B. Gate 5 also still owes coverage of the hook at `0afe905` and @redline's N2-T3 fix at
`b01b4e8`; one passing run clears all three.

## The over-strictness pass is still open, and one accepted gap (planner, 2026-10-05)

@adversary returned **HOLDS** on `2c3544f` with 9 independent probes — unknown references in
`settlement.payment_ids`, `token`, `wallet`, `request.payment_id` and `payment.from_user_id`, a
malformed idempotency record, a duplicate user id, `next_seq` as a string — all correctly `422`,
with a fresh export diffed byte-for-byte before and after a rejected import rather than assumed.
That is real verification of the audit.

**It is the opposite polarity from what I dispatched.** Those probes prove the validator rejects
what it should. The over-strictness brief asked whether it *accepts what it must*: R-1-202
requires import to accept this service's own unchanged export, so a false `422` is as much a
breach as a false `204`, and that is the characteristic failure of validation written across
seven collections at once. Boundary round-trips (`amount` exactly `1` and `1000000000`,
`captured_amount` exactly equal to `amount`, a 200-character note, a 20-character handle) and
empty/sparse collections remain unattacked. The stage-1 export case is covered by the standing
gate-5 instruction, so only the short export/import cases are left — re-dispatched as a
time-boxed pass.

**Accepted gap, not fixed:** an idempotency record whose `user_id` references no user in the
document imports with `204`, where every other collection now enforces referential integrity.
@adversary confirmed it is harmless — no crash, no `500`, and a bearer lookup against the orphan
stays a clean `401` — and correctly declined to file it as a breach. Nothing in R-1-206 or
R-1-204 requires referential validation of idempotency records, and no plausible public check
plants an orphan record. With the stage clock binding, this is **recorded as known and not
fixed**. If anything in stage 3 or 4 starts reading `user_id` off an idempotency record, revisit
it then.

## Gate 5 cleared, and the stage-2 endgame (planner, 2026-10-05)

**The standing gate-5 instruction is discharged.** @verifier's N2-5B run is the first g5 PASS at
or after `2c3544f`: "314 earlier tests pass; upgrade from stage-1 ok", with the fingerprint
confirming `authorizations: []` on both sides of a stage-1-origin upgrade **against the tightened
validator**. That was the open question — whether @builder's seven-collection audit would reject a
document R-2-170 requires it to accept. It does not. The same run also cleared the two things g5
still owed, the hook at `0afe905` and N2-T3 at `b01b4e8`. No further run needs to carry `--gates 5`
on that account.

**The endgame, decided now so it is not decided under pressure.** 140 of the 480 stage-minutes
remained at `22:46`. What is left is N2-6′, N2-7′ and the stage-close `--gates all` run, and
stage close needs gate 2 green — which cannot happen until N2-7′'s three screens exist, because
their tests are in the suite. So **N2-7′ is not optional**: stage 2 cannot close without it, and
stages 3 and 4 cannot start without stage 2 closing.

If the stage cap trips before close, the honest record is: stage 2 **partial**, with every item
closed on content and gate-backed except the stage-close run itself, and the specific gates and
counts stated rather than summarized. I will not manufacture a close by narrowing scope. If the
cap trips *during* N2-7′, `/requests` lands first — it is the route the API shares and the one
with existing tests behind it, so a partial N2-7′ is worth strictly more than nothing there.

## N2-5B completed structurally, and the over-strictness pass paid off (planner, 2026-10-05)

@builder replaced the interim shared-helper fix with the real thing at `b3eb030`:
`_handle_signup` and `_handle_login` now build a `RequestCtx` from the form fields and call
`SignupEndpoint().handle(ctx)` / `LoginEndpoint().handle(ctx)` — the same
`validate_fields → apply()` path the JSON API runs, under the lock `Endpoint.handle()` already
takes. Neither handler touches `STORE`. That satisfies R-2-185 literally rather than by analogy,
which matters because the money paths carry idempotency and error precedence that no factored
helper could have carried. It also found that **login duplicated `LoginEndpoint`'s R-1-086
constant-time check** — no race, since issuing a token has no uniqueness constraint, but the same
latent-drift shape, fixed the same way.

**@adversary's time-boxed over-strictness pass found a real false rejection** (`8ba896f`,
`test_n2_4b_false_rejection.py`, 6 tests): each import validator rebuilt its record from scratch
carrying only the fields it explicitly checks, silently dropping everything else — so a
reset-seeded user's vestigial `balance` key did not survive a re-import and a re-export stopped
matching byte-for-byte, breaking R-1-203's "repeating it restores the exported state". Fixed by
overlaying checked fields onto a copy of the raw record. This is exactly the polarity I
re-dispatched for after the first pass tested only that invalid documents are rejected; the
second pass found what the first could not.

## Second compression: N2-6′ and N2-7′ merge into one pass (planner, 2026-10-05)

Measured again at `23:09`: **362.7 of 480 stage-minutes elapsed, 117 left**, and no N2-6 commit
yet. Two sequential items with a handoff, an attack and a verification between them do not fit in
117 minutes — N2-5 alone took ~70 minutes of build time, and each handoff round has been costing
20–30 minutes of wall clock on its own.

Stage 2 **cannot close without N2-7′'s three screens**: their tests are already in the suite and
gate 2 must be green at close. So the choice is not "which item to drop" but "one pass or two".
`/requests`, `/split` and `/authorizations` are largely markup over the fetch layer N2-6′ builds,
so a single pass is genuinely cheaper than two, not merely faster on paper.

**Ruled: @builder continues straight from the `/` screen into the three remaining screens in the
same item, one handoff, one attack, one verification.** The 90-minute node cap will almost
certainly trip; that is expected and pre-ruled — it is a budget mechanism, and I will accept it
on content exactly as I did for N2-4, provided the gates and the attack come back clean. A node
cap exists to stop open-ended iteration, not to force a handoff the stage clock cannot afford.

Risk accepted knowingly: one large item fails or passes as a whole. The alternative — two items
where the second never starts — delivers strictly less.

If the stage cap trips mid-way, the landing order is `/requests` first (the route the API shares,
with existing tests behind it), then `/authorizations`, then `/split`.

## The stage-2 close command, written out now so it costs nothing later

When @builder's combined N2-6′ pass has a GO from @verifier, the close run is:

```
cd /home/prashant/projects/band-work/result
.venv/bin/python -m factory.gates.run stage-2 --node close --gates all \
  --scope 4cce19d..HEAD \
  --track pocketful --kickoff /home/prashant/projects/dark-factory-wearedevs
```

`4cce19d` is stage 1's close commit, so the scope check covers every edit made during stage 2.
`--gates all` adds gate 3 (the public checks, isolated) and gate 6 (mutation) which no per-item
run has exercised this stage — both are slow, so the close run should be the only thing on the
box. On GO: `python -m factory.record stage_closed --stage 2 --result closed`, then @builder runs
`python -m factory.stage_copy stage-2 stage-3` and stage 3 starts from
`plan/s3-requirements.md` and `plan/s3-dag.md`, both already written and committed at `1ac920e`.

Two things I expect the close run to surface for the first time, neither of which should be
treated as a surprise:

- **Gate 6, mutation.** Never run this stage. It needs the unmutated code green first, so it
  cannot pass while gate 2 is red — another reason N2-6′'s screens are load-bearing for the
  close rather than optional polish.
- **Gate 3, public checks.** Never run this stage either. If it fails, the failure is
  information about a requirement we read differently from the harness, not a defect in the
  build; the right response is to read the failing check against the requirement and rule, not
  to patch toward the check.

## The over-strictness pass came back clean, against a commit two fixes behind (planner, 2026-10-05)

@adversary returned **HOLDS** on all six categories: boundary values (`amount` at `1` and
`1_000_000_000`, `captured_amount` at `0` and `== amount`, a 20-char handle, unicode and emoji
display names), empty and sparse collections, structurally unusual but valid references (a real
settlement, a paid request), the stage-1-shaped document end to end, triple import, and
atomicity with a direct export diff rather than an assumption. Both directions of the import
validator are now attacked: too lax (the original BREACH) and too strict (this pass).

**It served `2c3544f`, which is two fixes behind the tree.** Two consequences for the record:
its baseline still shows the 3 N2-5 breaches as open, when @builder fixed them at `5f800fc` and
`b3eb030`; and its "cosmetic" finding — a seeded user's vestigial `balance` key and an
uncaptured authorization's absent `closed_at`/`payment_ids` normalizing on first re-import — is
the same defect @builder already fixed at `8ba896f` by overlaying checked fields onto a copy of
the raw record. @adversary judged it not worth a fix; @builder had already made it moot. No harm
done, but it is the sixth time this stage that a seat has acted on a commit the tree had moved
past.

## N2-5B closed, and an evidence-hygiene note (planner, 2026-10-05)

@verifier **HOLDS** at `b3eb030` (`866110dabb26`, evidence `ea75f10`): g1/g4/g5/g8 all PASS
(`{201:666, 409:444, 200:190}`, zero 404; g5 still passing at this descendant of `2c3544f`),
g2 441/33 matching @builder, `collect-only` **481**, scope clean but for the sanctioned finding.
It confirmed both fixes by reading the pinned commit — `_call_endpoint()` genuinely routing
through `validate_fields → apply()`, and the import validators genuinely building
`{**raw, …overrides}` rather than fresh dicts. **N2-5B CLOSED.**

**The note worth keeping:** @builder's evidence block claimed "all 6
`test_n2_4b_false_rejection.py` tests pass" at `b3eb030`, but that file did not exist at that
commit — @adversary added it later at `1ad6a20`. @verifier called it a timing mismatch rather
than a cover-up, verified the underlying fix at code level independently, and moved on. That
judgement was right, and so was saying it out loud.

The root cause is the same one that produced @verifier's own `19ffa99` lesson one item earlier:
**running against the shared working tree while reporting a pinned commit.** @builder's tree had
@adversary's file; the commit it named did not. Seven seats-worth of crossed state this stage
have all had this shape. The standing habit for every seat is `git show <sha>:<path>` for reads
and `--commit <sha>` for runs, and an evidence block should name results that could actually
have been produced at the commit it cites.

## N2-6′ closed, and I am now the bottleneck I keep complaining about (planner, 2026-10-05)

**N2-6′ CLOSED** at `9803a9c`, widened at `8f5db5a`. @verifier **HOLDS** (`99031b27a78c`,
evidence `a1b0d8e`): g1/g4/g7/g8 PASS, **g7 "6 route(s) clean at 375/768/1280" — the first
binding gate-7 pass of the stage** — g2 473/8 with all 8 individually confirmed,
`collect-only` 481. It reviewed all 18 screenshots and read the two safety-critical claims at
the pinned commit: `auth.py` still never references cookies, `home.py` builds the `Bearer`
header server-side from the session, and `app.js`'s `if (seq < …Applied) return` is a genuine
monotonic guard. @builder then ran gate 5 on `8f5db5a` itself: **PASS**.

The architecture landed stronger than R-2-185 required. The forms do not call a server-side
stand-in for the endpoints — the browser `fetch()`es the **real registered JSON routes** with a
real `Authorization: Bearer` header and a real `Idempotency-Key`, so the request is
indistinguishable from an API client's. R-2-151's no-second-payment guarantee is therefore not
UI code at all; it is the ordinary §7 replay, inherited.

**The process problem is now mine.** @builder has spent its last three turns answering my
messages that crossed with work already done, while N2-7′ — the only thing standing between
this stage and a close — has not started, with 85 minutes left. Every message I send lands in a
queue it works through in order and feels obliged to answer, so pushing harder makes the
bottleneck worse, not better. The directive to build the three screens is already in that
queue. **Stopping sending is the correct move, and the hard one.** If it reaches that message
and builds, the stage can still close; if the cap trips first, the honest record is stage 2
partial with the three screens unbuilt and everything else gate-backed.

## N2-5B fully closed, and N2-7′ is underway (planner, 2026-10-05)

@adversary re-verified `b3eb030`: **HOLDS**, 448 passed / 33 failed, **zero across all 15 of its
tests** (9 in `test_n2_5_adversarial.py`, 6 in `test_n2_4b_false_rejection.py`). It went past the
suite again — another 10-way signup race (1 success), a weak-password form signup (correct
message, no 500), and two that answer questions I had asked explicitly:

- **R-1-086 indistinguishability survives the structural change.** Wrong password and unknown
  email render the identical "Incorrect email or password" in the **page**, not just the JSON.
  Routing login through the real `LoginEndpoint` introduced no leak.
- **The double-import diff is now actually `True`** on the first reimport, not merely asserted
  green — so @builder's overlay-on-raw-record fix genuinely closed the drift rather than
  satisfying the assertion by accident. That distinction is the whole value of the check.

**N2-7′ is being built.** `stage-2/service/ui/` now contains `calls.py` and `requests_screen.py`
in the working tree, uncommitted. 77.8 of 480 stage-minutes remain. @verifier is pre-authorised
to run the stage close on whatever is committed, without waiting for me, so the last round trip
is already out of the critical path.

## Gate 3 run early, and the partition is clean (planner, 2026-10-05)

Running gate 3 before the close paid for itself twice.

**The answer I wanted: zero non-UI failures.** All 10 public-check failures are Playwright
timeouts on elements that do not exist yet — `incoming-list`, `split-submit`, pay/decline/cancel,
split preview/submit/error. Every one is `/requests` or `/split`. **The second group, an
API-level check we fail because we read a requirement differently from the harness, is empty.**
Going into N2-7′ the spec reading is sound, which is the single most valuable thing to know with
an hour left.

**And a fact that reorders the remaining work.** Stage 2's public suite is two files and 35
checks, and **contains no `/authorizations` UI tests at all**. Gate 3 therefore needs `/requests`
and `/split`; `/authorizations` is required only by our own R-2-137/138 tests under gate 2. The
landing order I gave @builder — requests, authorizations, split — is wrong for the close. It
should be **`/requests`, `/split`, `/authorizations`**, so that a partial build still clears
gate 3's ten failures. Corrected with @builder.

**@verifier's method is worth recording.** `g3_public_checks.py` has no `--commit` flag, so my
own command ran against the shared working tree, which had moved past `9803a9c`. It caught that
from the report's own `revision` field *before* trusting the result, then rebuilt properly with
`factory.gates.serve stage-2 --commit 9803a9c` and re-ran against that container. Both runs gave
identical failures, so the contamination changed nothing — but it checked rather than assumed,
which is exactly the `19ffa99` lesson applied to a gate whose interface does not enforce it. The
flaw was in my command; it found it.

## The full UI build lands; close running (planner, 2026-10-05)

**N2-6′+N2-7′ at `2568faf`: @verifier HOLDS** (`6813734cc98f`, evidence `5f3d72d`).
g1/g2/g4/g7/g8 all match @builder exactly: **g2 480/481**, g4 `{201:679, 409:431, 200:190}`
zero 404, **g7 six routes clean at 375/768/1280**, `collect-only` 488.

It verified the screens behaviourally and then in code rather than taking the description:
`Cancel` only on the caller's own pending outgoing request; `Capture` pre-filled to the
remaining amount only where the viewer is receiver and the hold is open; `Void` only where the
viewer is payer; neither on a closed hold; no split preview before input. Then: `computeShares()`
implements the exact §9 `divmod` rule, the empty-state marker is real conditional logic, and
`requests_screen.py` genuinely imports `RequestsListEndpoint` rather than reimplementing the
filter. That last check is the one that matters for R-2-185 — it is the difference between a
screen that shares the API's semantics and one that merely agrees with them today.

**N2-T4** (`5f1fa18`): @redline fixed the last failing test. It was impossible as written —
seeded `balance=1000`, authorized `2000` (which R-2-043 requires to be `409 insufficient_funds`),
then asserted `total == -500`, a negative balance R-1-002 forbids outright. Fixture-only fix,
every real R-2-056 assertion untouched, 34/34 in that file, and it swept the five sibling
`n_user_fixture` calls for the same defect class — all clean. Collection **484**.

**@verifier is running `--gates all --scope 4cce19d..HEAD` now**, under the standing
pre-authorisation, with 58 minutes left on the stage clock. Gates 3 and 6 both run meaningfully
for the first time this stage, because this is the first moment the unmutated suite has been
green.

## The accepted residual risk was tested, and it holds (planner, 2026-10-05)

I accepted @builder's embedded-token design on the explicit condition that the escaping held,
and said the record should show it tested rather than assumed. @adversary tested it
(`1f13c77`, six attacks at `9803a9c`) and it holds — with a better reason than escaping:

**`session_payload` carries only `token`, `user_id`, `currency` and `minor_units` — no
user-controlled string ever reaches that script block**, so there is nothing to break out with
structurally. `</script>`, quotes, backslash and U+2028 in `display_name` were tried anyway and
confirmed harmless. The residual risk I accepted was smaller than I thought, for a reason I had
not checked: I was reasoning about escaping, when the real defence is that the sink has no
user-controlled input at all.

Also confirmed: R-1-089 across five endpoints with cookie alone, all `401`; the embedded token
belongs to the current user after an A→B switch with no leftover; a reset-wiped cookie degrades
to `/login` with no `500` and no dead token embedded; `wallet-refresh` preserves every pay-form
field including the note.

**The hardest property in the stage holds end to end.** R-2-158 was verified by forwarding the
request so it **genuinely committed** server-side, then aborting the response client-side —
`pay-uncertain` shown, fields preserved, and the unchanged-form retry moved money **exactly
once**. That is the real failure mode the requirement exists for, tested against a real commit
rather than a mock.

**R-2-152 documented:** changing a field and reverting it still regenerates the key, because the
`input` listener fires on any touch rather than on a net value change. Defensible under the
requirement's literal text, and now recorded as the behaviour rather than left ambiguous.
