# Stage 2 status

Stage 1 closed at `4cce19d` (@verifier GO `9bfb5d357b8c`). `stage-2/` starts as a
copy-forward of the frozen `stage-1/`, so every R-1-001 … R-1-244 requirement arrives
satisfied and must stay satisfied — that is gate 5's job from here on.

| id | state | commit | evidence |
|---|---|---|---|
| N2-0 | **done** | `721295c` (+ `0ba3d8f` cost) | @builder. `git diff --stat 4cce19d:stage-1 721295c:stage-2` is **empty** — the trees are identical, nothing differs but the path prefix — and `stage-2/tests/invariants/hook.py`, `stage-2/Dockerfile`, `stage-2/RUN.md` are all present. @builder reported both checks rather than asserting the copy worked, and stopped without starting N2-1. |
| N2-T | **READY** | `36bcb2d` | 431 tests (up from stage 1's 314), 0 collection errors, red for the right reason (`httpx.ConnectError`, no service). Planner-verified below. |
| N2-1 | **built, attacked, gates re-run** | `15b99f5` (+ `f8c6462` code, `e3f81bb`/`5b6df67` attack) | Holds model. @adversary **HOLDS** (`a5a39df7c0a0`, 15 attacks). @verifier re-ran tagged: **g1 PASS, g4 PASS, g8 PASS**; scope clean but for the already-ruled sanctioned finding; collection ratchet **447 ≥ 431**. Awaiting the formal GO token — see the two findings below. |
| N2-2 | dispatched | — | `POST /authorizations`, `GET /authorizations`, R-2-014/015/016/018 + R-2-040…046 + R-2-080…084 (R-2-012/013/017 already landed in N2-1). @builder. |
| N2-3 | planned | — | — |
| N2-4 | planned | — | — |
| N2-5 | planned | — | — |
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
