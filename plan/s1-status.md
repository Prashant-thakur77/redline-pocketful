# Stage 1 status

| id | state | commit | evidence |
|---|---|---|---|
| N1-T | READY, 1 rework open | 6663728 | 195 tests, all 164 R-1-* ids referenced (verified by planner); hook `snapshot` must become a cross-stage fingerprint — see N1-T.1 |
| N1-T.1 | dispatched | — | hook `snapshot` returns the raw export doc, so gate 5 `before == after` will fail on a correct stage-2 upgrade; storm never reaches the funds boundary |
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
