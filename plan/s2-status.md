# Stage 2 status

Stage 1 closed at `4cce19d` (@verifier GO `9bfb5d357b8c`). `stage-2/` starts as a
copy-forward of the frozen `stage-1/`, so every R-1-001 … R-1-244 requirement arrives
satisfied and must stay satisfied — that is gate 5's job from here on.

| id | state | commit | evidence |
|---|---|---|---|
| N2-0 | **done** | `721295c` (+ `0ba3d8f` cost) | @builder. `git diff --stat 4cce19d:stage-1 721295c:stage-2` is **empty** — the trees are identical, nothing differs but the path prefix — and `stage-2/tests/invariants/hook.py`, `stage-2/Dockerfile`, `stage-2/RUN.md` are all present. @builder reported both checks rather than asserting the copy worked, and stopped without starting N2-1. |
| N2-T | **READY** | `36bcb2d` | 431 tests (up from stage 1's 314), 0 collection errors, red for the right reason (`httpx.ConnectError`, no service). Planner-verified below. |
| N2-1 | dispatched | — | Holds model: `total`/`available`/`held`, fixture `authorizations` + `authorization_ttl_seconds`, reset validation, clock-exact expiry on read. @builder. |
| N2-2 | planned | — | — |
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
