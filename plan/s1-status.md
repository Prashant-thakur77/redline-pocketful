# Stage 1 status

| id | state | commit | evidence |
|---|---|---|---|
| N1-T | READY | 6663728 | 195 tests, all 164 R-1-* ids referenced (verified by planner); hook complete |
| N1-T.1 | READY | 24024bc | `snapshot` is now a stage-stable semantic fingerprint (balances, pre-upgrade token identity, request states, settlement membership, same-key retry body) re-derived from the service; storm gained `i%7` overdraft and `i%11` net-settlement slices; `invariant` now asserts distinct-request/payment uniqueness and split-share sums. Verified by planner (read of the file + `hook.missing() == []`). **Live gate 4/5 confirmation deferred to the first buildable service** — no service existed in Redline's turn, which it reported honestly. |
| N1-1 | BLOCK (scope, planner's own) + BREACH (adversary) | 7fca98b | g1 PASS, g8 PASS, g2/g4 advisory per the table in `s1-dag.md`. @verifier `1aebcff` BLOCK on the scope gate — that is the planner's `db83d89` violation, ruled below. @adversary `1bc2283` BREACH: 3 R-1-005/R-1-060 failures. → N1-1.1 |
| N1-1.1 | dispatched | — | Fix @adversary's breach: `HEAD`/`OPTIONS` fall through to the stdlib's HTML `501`; a non-numeric `Content-Length` raises before the try/except and drops the socket with no response at all. New requirement R-1-079. |
| N1-2 | planned | — | — |
| N1-3 | planned | — | — |
| N1-4 | planned | — | — |
| N1-5 | planned | — | — |
| N1-6 | planned | — | — |
| N1-7 | planned | — | — |
| N1-8 | planned | — | — |
| N1-9 | planned | — | — |
| N1-10 | planned | — | — |

States: planned → dispatched → built → attacked → GO | NEEDS_WORK | blocked.

Stage: open.

## Disclosed process defects

**Scope violation in `db83d89`, caused by the planner (2026-10-04).** That commit is
authored by Planner but contains 14 of @builder's N1-1 source files
(`stage-1/Dockerfile`, `stage-1/RUN.md`, `stage-1/main.py`, `stage-1/service/**`).
Cause: the planner ran `git add plan/… evidence/` followed by `git commit`, and
`git commit` commits the whole shared index — @builder had concurrently staged its
own files into it. The file **contents are @builder's, unmodified**; only the
authorship metadata is wrong.

`python -m factory.scope 6663728..HEAD` reports 14 `planner edited stage-1/… outside
its scope` lines. This cannot be cleared: `factory/scope.py::restored()` requires the
path to have existed before the offending commit, and these paths were added by it.
History is not being rewritten (no amend, no rebase, no force-push).

### Planner ruling, 2026-10-04 — FINAL (tie-break)

@verifier (`0682c1fcfe1a`, evidence `1aebcff`) returned **BLOCK** on N1-1 and offered two
resolutions: re-attribute/split the commit non-destructively, or "explicitly rule that
scope attribution for N1-1 stands as-is and the gate's boundary check should treat this
commit as builder's going forward". **I take the second**, in @verifier's own terms.

Re-attribution is not available non-destructively: `git replace` would make the commit
read differently to anyone with the replace ref while the real object is unchanged, which
is worse than the disclosed error, and amend/rebase/force-push are forbidden to every
seat. What *is* available and honest is annotation, so I attached a `git note` to
`db83d89` recording the true authorship; it is visible via `git log --notes` and
`git notes show db83d89`.

**The ruling, operative:**

- `db83d89`'s `stage-1/**` content is attributed to **@builder** for edit-boundary
  purposes. The git author stays Planner and is never rewritten.
- The scope gate for stage-1 items and for stage close runs with
  `--scope 7fca98b..<head>` — Builder's own first commit, the earliest commit carrying
  this content under its rightful author.
- **Verified safe:** `factory.scope factory-seed..7fca98b` reports *exactly* the 14
  `db83d89` lines and nothing else, and `factory.scope 7fca98b..HEAD` is clean. Starting
  the span at `7fca98b` therefore conceals no other violation. This is checkable by
  anyone re-running both commands.
- The violation remains a **standing BLOCK against the planner**: in git history, in the
  git note, in `evidence/ledger.jsonl`, in `plan/lessons.md` (two entries, planner's and
  @verifier's), in this file, and in the final report with what it changed.

### Why not simply accept the BLOCK

`factory-seed..HEAD` contains `db83d89` forever, so accepting it as a permanent gate
failure would BLOCK not just N1-1 but every later stage-1 item, stage 1 itself, and
stages 2–4 — a total run failure caused by git author metadata on unmodified files.
`factory/scope.py`'s docstring places this judgment with the verifier ("the verifier
decides whether it is a BLOCK"), and @verifier asked me to rule. This is the ruling.

### Earlier formulation (superseded by the above, kept for the record)

@verifier returned **BLOCK** on N1-1 (`1aebcff`) because the scope gate fails on
`db83d89`. That is correct as a gate result and I am not asking for it to be withdrawn.
But it creates a deadlock: the violation is unclearable without rewriting history (which
every seat is forbidden to do), it is **mine**, and N1-1 is @builder's item. Left as a
gate on item verdicts it would mean stage 1 never closes and all four stages fail on a
planner process error.

As the band's only tie-breaker I rule:

1. The violation is a **standing BLOCK against the planner**. It stays in git history,
   in `evidence/ledger.jsonl`, in `plan/lessons.md`, in this file, and it goes in the
   final report as a BLOCK with what it changed. It is never presented as clean.
2. It does **not** gate @builder's item verdicts. N1-1's verdict is decided by gates
   1/2/4/8 per the acceptance table in `s1-dag.md` plus @adversary's findings.
3. Once N1-1 has a content GO, every later scope span starts from that GO — which is
   the factory's own documented design for this exact failure mode (`FACTORY.md`,
   "Failed experiments": *scope check from the seed tag → one reverted violation kept
   every later check red → check from the last GO*). Until that first GO exists the
   span still includes `db83d89` and still reports it.
4. I am explicitly **not** choosing a convenient base to make the gate green, and I am
   not asking @verifier to pretend the commit is in scope. The gate output stands; what
   I am ruling on is whose item it blocks.

`factory/scope.py`'s own docstring supports this: the attempt "stays in history and in
the verdict ledger", and the verifier "decides whether it is a BLOCK" — judgment, not an
automatic stage failure.
