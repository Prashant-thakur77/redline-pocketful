# Stage 4 work plan — `stage-4/`

`stage-4/` starts as a copy-forward of the closed `stage-3/`
(`python -m factory.stage_copy stage-3 stage-4`), so every R-1-*, R-2-* and R-3-*
requirement is satisfied on arrival and must stay satisfied (gate 5).

Stage 4's checks are mostly hidden, like stage 3's, so test effort weights here. There are
**ten idempotent write paths** at this stage: stage 1's five, authorizations and captures
from stage 2, corrections from stage 3, and refunds and correction batches here. Every one
of them must independently satisfy §7 — that count is itself a requirement worth testing.

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| N4-T | Tests and gate hook for refunds and batch corrections | all R-4-* | — | redline |
| N4-1 | `POST /payments/{id}/refunds` — receiver-only, target eligibility, cumulative cap, opposite-direction payment with `refund_of` | R-4-010 … R-4-022 | N4-T | builder |
| N4-2 | Refund funds semantics: moves from the receiver's **available**, atomic, never reopens a request/authorization, never restores a released hold | R-4-023 … R-4-028 | N4-1 | builder |
| N4-3 | Stage-4 correction limits: captures and refunds `linked_payment_immutable`; a correction may not reduce a payment below its refunded amount (`refund_exceeds_payment`); correction debits checked against available | R-4-030 … R-4-036 | N4-1 | builder |
| N4-4 | `POST /correction-batches` — operator auth, 1..32 distinct payment ids, per-item validation in input order | R-4-040 … R-4-048 | N4-3 | builder |
| N4-5 | Settlement completeness: correcting any member requires every member (`incomplete_settlement`); members share identical effective instants across offset spellings | R-4-050 … R-4-054 | N4-4 | builder |
| N4-6 | Batch error precedence: item errors → settlement completeness → current available funds → historical total and available at every boundary; rejected batch changes nothing | R-4-055 … R-4-060 | N4-5 | builder |
| N4-7 | Batch success shape: shared `recorded_at` strictly later than every member's previous, `correction_batch_id` on each revision, input order, replay returns the original with 200 | R-4-061 … R-4-068 | N4-6 | builder |
| N4-8 | Snapshot and receipt immutability across refunds and batches: earlier tokens page frozen entries, original payments and retries unchanged, new statements reflect new revisions | R-4-070 … R-4-074 | N4-7 | builder |
| N4-9 | Export/import accepting stage-1 … stage-3 exports, retaining settlement membership, corrections, refunds and snapshots | R-4-080 … R-4-084 | N4-8 | builder |
| N4-10 | UI for refunds and corrected amounts; gate 7 non-vacuous | R-4-090 … R-4-094 | N4-2 | builder |
| N4-11 | Hardening: concurrent corrections sharing any expected revision, refund races against corrections, conservation under the full ten-path storm | R-4-001 … R-4-006, R-4-100 … R-4-106 | N4-9, N4-10 | builder |

Dispatch order: N4-T → N4-1 → (N4-2, N4-3) → N4-4 → N4-5 → N4-6 → N4-7 → N4-8 → N4-9 → N4-10 → N4-11.

Gates per item: `--gates 1,2,4,8 --commit <sha>`; N4-10 adds gate 7.

## Carried structural warnings

- **Gate 7 non-vacuous** (`plan/s2-dag.md` G7-1 … G7-4): the `g7` ledger event must exist and
  name the routes visited. A missing record is a close failure, not a pass.
- **Gate runs are serialized** and dispatched with `--commit <sha>` (`plan/lessons.md`,
  `7c85099` and `ee723d1`): one seat builds containers at a time, and recorded counts must
  describe committed state.
- **No stage may pass the next stage's checks.** Stage 4 is last, so gate 3 should claim 4 with
  nothing above it; for stages 1–3 the absence of overshoot is as much a requirement as the pass.

## The three traps this stage

1. **Refunds interact with holds without touching them.** A refund moves existing money from the
   receiver's *available* funds and must never reopen a request or authorization or restore a
   released hold. The tempting implementation reuses the capture or correction path and silently
   re-opens one of those.
2. **`refund_exceeds_payment` is reachable from two directions** — a refund that exceeds the
   current corrected amount, and a *correction* that would reduce a payment below what has
   already been refunded. Both give the same code, and the second is easy to miss entirely.
3. **Batch affordability is the combined effect of all proposed revisions**, not each in turn.
   A batch where two corrections are individually unaffordable but jointly fine must succeed,
   and one where each is fine alone but the combination overdraws must fail — the same shape as
   stage 1's R-1-227 net-settlement rule, which @adversary's bidirectional test caught there.
