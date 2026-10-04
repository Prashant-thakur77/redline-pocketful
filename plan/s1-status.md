# Stage 1 status

| id | state | commit | evidence |
|---|---|---|---|
| N1-T | READY | 6663728 | 195 tests, all 164 R-1-* ids referenced (verified by planner); hook complete |
| N1-T.1 | READY | 24024bc | `snapshot` is now a stage-stable semantic fingerprint (balances, pre-upgrade token identity, request states, settlement membership, same-key retry body) re-derived from the service; storm gained `i%7` overdraft and `i%11` net-settlement slices; `invariant` now asserts distinct-request/payment uniqueness and split-share sums. Verified by planner (read of the file + `hook.missing() == []`). **Live gate 4/5 confirmation deferred to the first buildable service** — no service existed in Redline's turn, which it reported honestly. |
| N1-1 | dispatched | — | g8 PASS, within caps |
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
