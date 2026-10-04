# Stage 3 work plan — `stage-3/`

`stage-3/` starts as a copy-forward of the closed `stage-2/`
(`python -m factory.stage_copy stage-2 stage-3`), so every R-1-* and R-2-*
requirement arrives satisfied and must stay satisfied — that is gate 5's job.

**This stage and stage 4 carry the most hidden checks, so test effort is weighted here.**
@redline's N3-T is the largest single item in the run: bitemporal reads have far more
reachable states than any stage-1 endpoint, and a thin suite here is the most likely way
the run fails a check nobody wrote.

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| N3-T | Tests and gate hook for bitemporal reads, corrections, snapshots and historical holds | all R-3-*, carried R-1-*/R-2-* | — | redline |
| N3-1 | Revision model: revision 1 for every existing and seeded payment, append-only history, `GET /payments/{id}/revisions`, seeded `created_at` and opening balances | R-3-003, R-3-004, R-3-010…019, R-3-063, R-3-064, R-3-101, R-3-103 | N3-T | builder |
| N3-2 | `GET /me?as_of` — effective-time balance reconstruction | R-3-020…027 | N3-1 | builder |
| N3-3 | `GET /statement` — window, ordering, deltas, running balances, pagination independence | R-3-030…044 | N3-2 | builder |
| N3-4 | `POST /payments/{id}/corrections` — validation, precedence, the same-two-wallets movement, `stale_revision`, immutability of captures and settlement members | R-3-050…069 | N3-3 | builder |
| N3-5 | `known_at` revision selection across `/me` and `/statement` | R-3-070…077, R-3-038…041 | N3-4 | builder |
| N3-6 | Historical overdraft: boundary checking across every effective and event instant, with `insufficient_funds` taking precedence | R-3-002, R-3-059, R-3-060, R-3-118, R-3-133 | N3-5 | builder |
| N3-7 | Snapshot tokens: issue, freeze, page, scope to user and reset | R-3-005, R-3-080…091 | N3-5 | builder |
| N3-8 | Historical holds: hold timeline, `closed_at`, expiry at deadline, four-field historical view | R-3-110…120 | N3-6 | builder |
| N3-9 | Import of stage-1 and stage-2 exports; revision 1 synthesis for imported payments | R-3-102, R-3-100 | N3-1, N3-8 | builder |
| N3-10 | UI for statements and corrections, carried stage-2 screens intact | R-2-090…160 carried, s3 UI | N3-3, N3-4 | builder |
| N3-11 | Hardening: correction storm, snapshot-under-correction races, concurrent same-revision corrections | R-3-001, R-3-067, R-3-130…133 | N3-7, N3-8, N3-9 | builder |

Dispatch order: N3-T → N3-1 → N3-2 → N3-3 → N3-4 → N3-5 → (N3-6, N3-7) → N3-8 → N3-9 → N3-10 → N3-11.

Gates per item: `--gates 1,2,4,8`; items touching the browser also run gate 7.

## The three traps I expect to cost the most

1. **Revision 1 must exist for every payment that already exists**, including seeded ones,
   imported ones, settlement members and captures — not only for payments created after the
   correction endpoint was built. A service that synthesises revision 1 lazily will return an
   empty `revisions` list for an imported payment (R-3-063, R-3-102).
2. **`known_at` excludes, it does not zero.** A payment whose first revision was recorded after
   `known_at` contributes **nothing** — it is absent from the statement, not present with a zero
   delta. A zero-*amount* revision is the opposite case and **does** appear (R-3-071, R-3-077,
   R-3-039).
3. **The overdraft check is over boundaries, not over the end state.** A correction can leave
   every current balance nonnegative while driving one negative at an intermediate effective
   instant. Checking only the final balance passes the easy tests and fails the hidden ones
   (R-3-060, R-3-118).
