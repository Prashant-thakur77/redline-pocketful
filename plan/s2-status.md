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
| N2-3 | **HOLDS — closed on content, gate 2 advisory** | code `07052a8`, attack `0134811` | Capture and void. @verifier: **g1 PASS, g4 PASS, g8 PASS**, `collect-only` 447, scope clean but for the sanctioned finding; **the `404`-drop tripwire fired clean: zero `404`, down from 149.** @adversary then attacked the served `07052a8` directly — **18 attacks, HOLDS** (`0134811`): R-2-066 capture at `available == 0` succeeds (capture spends the wallet, never `available_for()`); R-2-056 partial final capture released exactly the remainder in the same step; R-2-005 capture-vs-void race over 15 trials had exactly one winner every time, landing only on `(0,0)` or `(1000,1000)`; a 15-way overcommit race on a 1000 remainder committed exactly ten 100s and returned `409 authorization_not_open` (never a stray `422`) for the rest; `403` beats `409` for a stranger on an expired hold; double void is idempotent. Gate 2 on the served commit: 409 passed, 48 failed, **zero in `test_n2_3_adversarial.py`** — the 48 remain the attributed UI/export-import set. HOLDS, not GO, per the ruling below. |
| N2-4 | **built, awaiting attack** | `b79a74b` | Export/import of holds and the stage-1 upgrade path: R-2-170…175. @builder closed the gap @verifier found (`snapshot.py` had **zero** references to `authorization`): `export_state()` now serialises `authorizations` + `authorization_ttl_seconds` verbatim, `validate_import_document()` defaults both when absent so a genuine stage-1 export imports clean, and `held`/`available` stay 100% derived at read time. g1 PASS, g4 PASS (`{201:667, 409:444, 200:189}`, **zero 404** — the tripwire held), g8 PASS; g2 advisory 400/447 with all 47 failures in the attributed baseline. **g5 FAIL, ruled a harness defect, not a service defect — see N2-T2.** @verifier **HOLDS** (`8eb4ee0644b4`, evidence `d6c8115`): g1 PASS, g4 PASS (`{201:678, 409:432, 200:190}`, zero 404), `collect-only` **458 ≥ 447**, scope clean but for the sanctioned finding, and all four traps independently re-confirmed by reading `snapshot.py`/`invariants.py`. **g8 FAIL — item wall clock 94.0 min > 90 cap. Planner ruling: trip accepted, item closed on content, no rework authorized** (see the governor ruling below). Dispatched to @adversary 2026-10-05 under node **N2-4A**. |
| N2-T2 | **content accepted, awaiting @verifier's g5 run** | `72bb489` (refines `278effd`) | Guard landed. I read the diff: probe runs **once** in `populate` (`GET /authorizations`, 200 → holds, 404 → not, with `assert status in (200, 404)` so an unexpected status is loud), recording both `_UPGRADE["holds"]` and `_UPGRADE["populated_url"]`; `snapshot` never re-probes and branches on the one stored flag; and the new-side liveness guard asserts `GET /authorizations` answers 200 on the side `populate` did **not** run against, fingerprinting nothing from it. Items 1–3 of my ruling are in. **Item 4 is not: the `body.get("held", 0)` / `body.get("available", body["balance"])` defaults at `hook.py:522` still default identically on both sides**, so a stage-2 regression that dropped those two fields from `GET /me` would compare equal here. **Accepted as a residual gap rather than a third round trip** — R-2-010 is directly covered by the gate-2 suite, so dropping either field turns gate 2 red regardless; gate 5 is defence in depth for it, not the only line. Recorded so it is not mistaken for complete coverage. Ratchet not in play — `hook.py` is not collected. **@verifier's g5 PASS (`a8c48245c67a`, evidence `10a49e3`, "314 earlier tests pass; upgrade from stage-1 ok") was run at `278effd`, the superseded first pass, not at `72bb489`** — my hold message crossed with the run. That PASS is real but proves only that the spurious 404 is gone; it does not exercise the guard, because `72bb489` changes the probe itself (`/me`+`held` → `GET /authorizations` 200/404) and adds the liveness assertion. **g5 must be re-confirmed at `72bb489` or later.** Folded into @verifier's next scheduled run rather than a dedicated container cycle; the stage-close `--gates all` at HEAD covers it as a backstop. |
| ~~N2-T2 (first pass)~~ | superseded | `278effd` | @redline's capability probe is exactly the design I specified: probe once in `populate` (`GET /me`, test for the `held` key), record the outcome, branch `snapshot` on the recorded values so both sides fingerprint the same shape; the hold-building block moved under `if supports_holds:` and the capture replay is `None`-guarded. Verified by reading the diff. **But the anti-silent-downgrade guard I required is absent**, and a second instance of the same hole exists at `hook.py:522` (`body.get("held", 0)` / `body.get("available", body["balance"])` default identically on both sides, so a stage-2 regression that dropped those fields would compare equal and pass). Returned to @redline 2026-10-05 for the guard only; no other change wanted. | Gate-5 hook is not cross-version. @builder's g5 log: `upgrade check failed: AssertionError: {"error":{"code":"not_found","message":"no such endpoint: POST /authorizations"}}` (`evidence/gates/s2/N2-4-g5-20261004T205427-c36f.log`). Confirmed against `factory/gates/g5_regression.py:22-37`: gate 5 builds the **previous** stage folder as a second container and runs `populate(old_url)` and `snapshot(old_url)` against it, then `carry`, then `snapshot(new_url)`, requiring `before == after`. `stage-2/tests/invariants/hook.py:451` calls `POST /authorizations` unconditionally and `:551` / `:560` read `GET /authorizations` and replay a capture — none of which exist on stage 1, by design (R-2-170's premise). @builder is right and could not fix it: `tests/invariants/hook.py` is @redline's boundary. **Planner ruling: hook defect. N2-4's service work stands.** @redline, 2026-10-05. |
| N2-5 | dispatched | — | UI shell and design system: R-2-090…093, R-2-100…111, R-2-120…125. @builder, 2026-10-05. This is the critical path: gate 2 stays red for every item until screens exist, so the ~48 outstanding failures cannot clear before N2-5…N2-9 land. |
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
