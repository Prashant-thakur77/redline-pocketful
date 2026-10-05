# Official dispatch (pocketful, stages 1–4)

The single human input of the judged run. Paste the block into the new room addressed to @Planner, or send it with `make dispatch-official REPO=/abs/result` (fills `{{REPO}}` and `{{KICKOFF}}`). Track detail belongs here, never in a mandate.

```text
@Planner Build the pocketful track, stages 1 through 4, into this repository.

Repository (absolute): {{REPO}} — every seat works and commits here. Python: {{REPO}}/.venv/bin/python.
Task package (read-only): {{KICKOFF}}
Specification: {{KICKOFF}}/pocketful/spec/stage-1.md, stage-2.md, stage-3.md, stage-4.md. Read every file in full; it is the only source of truth. Paste the requirements you derive into every handoff.
Do not open {{KICKOFF}}/pocketful/test/ or any other shipped test: build to the specification, including what no example shows. The public checks are one gate, run only by @Verifier at stage close.

Output: stage-1/ … stage-4/, each a complete service with Dockerfile, RUN.md and tests/. Each builds from its Dockerfile alone, serves HTTP inside a container with no outbound network, 2 vCPU and 2 GiB, listens on PORT (default 8080), is healthy within 60 s, and stays correct with 50 requests in flight. Each stage folder keeps every earlier stage's requirements and must not contain later-stage work: stage N must not pass stage N+1's checks.

Order of work per stage:
1. @Planner writes plan/sN-requirements.md (numbered R-N-nnn, invariants first, then everything a careful reader finds: error precedence, limits, idempotent replays, concurrency, pagination, export/import, upgrades from populated state) and plan/sN-dag.md.
2. @Redline writes tests from those requirements before any implementation, plus tests/invariants/hook.py: setup resets to a seeded fixture with several users; operation performs a random mix of the stage's money-moving calls with an idempotency key derived from i, so a repeat is a retry; invariant checks the conservation rules below; populate/snapshot/carry use export and import; UI_ROUTES and ui_login once the browser product exists.
3. @Builder implements item by item. @Adversary attacks each item. @Verifier runs the gates: items 1,2,4,8; stage close "all" with --track pocketful --kickoff {{KICKOFF}}.
4. Only @Verifier's GO closes an item; only a stage-close GO closes a stage. Then @Builder copies the folder forward and the next stage starts. Put the most test effort into stages 3 and 4, whose checks are mostly hidden.

Invariants, first in every stage:
- Money is never created, destroyed or spent twice: the sum of all balances always equals the total seeded by the last reset, under concurrent transfers, retries and rounding.
- No balance is ever negative, not even transiently.
- A request moves money at most once; a replayed write returns the original result and moves nothing.
- Every amount is an exact integer count of minor units; split shares sum exactly to the amount.

Browser product (from stage 2): it must look like a calm, trustworthy consumer finance app — available funds as the clearest number, a recent-activity feed, a send/request form with a confirm step, pending/settled/uncertain states shown distinctly, people and amounts formatted for people. Seed realistic demo data through the fixture so the first screen is never empty.

You will get no further input. Resolve every question inside the band. When all four stages are closed, or the budget stops you, post a final report with per-stage results, costs, and every BLOCK or NEEDS_WORK verdict and what it changed.
```
