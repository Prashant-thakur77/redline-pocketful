# Stage 1 work plan — `stage-1/`

Owner of every build item is @builder; @adversary attacks each item on handoff;
@verifier runs gates 1,2,4,8 per item and `--gates all` at stage close.
@redline owns `stage-1/tests/` including `tests/invariants/hook.py` and writes
them all before N1-1 is dispatched.

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| N1-T | Tests and gate hook from the requirements, before any implementation | all R-1-* | — | redline |
| N1-1 | Runtime skeleton: Dockerfile, RUN.md, PORT/health, JSON conventions, error envelope, validation + precedence engine, serializable store | R-1-005, R-1-006, R-1-010…016, R-1-020…025, R-1-060…078 | N1-T | builder |
| N1-2 | Fixture model, `POST /_test/reset`, currency/minor units, seeded users, payments, requests, operators | R-1-030…033, R-1-040…050, R-1-025 | N1-1 | builder |
| N1-3 | Auth: signup with derived handle, login, bearer tokens, password hashing | R-1-034…037, R-1-080…092 | N1-2 | builder |
| N1-4 | Idempotency layer shared by all five write paths | R-1-100…111 | N1-3 | builder |
| N1-5 | `GET /me`, `POST /payments`, `GET /activity` and the feed contract | R-1-001…004, R-1-007, R-1-120, R-1-130…140, R-1-190…195 | N1-4 | builder |
| N1-6 | Requests: create, pay, decline, cancel, `GET /requests` | R-1-150…167 | N1-5 | builder |
| N1-7 | Splits and the exact share arithmetic | R-1-170…180 | N1-6 | builder |
| N1-8 | `POST /settlements`: operator permission, batch validation, net affordability, atomic commit | R-1-196, R-1-220…236 | N1-6 | builder |
| N1-9 | `GET /_test/export` / `POST /_test/import` round-trip of every durable fact | R-1-200…210, R-1-235 | N1-7, N1-8 | builder |
| N1-10 | Hardening: concurrency storm, 50 in flight, reset under load, error-precedence sweep | R-1-001…007, R-1-015, R-1-240…244 | N1-9 | builder |

Dispatch order: N1-T → N1-1 → N1-2 → N1-3 → N1-4 → N1-5 → N1-6 → (N1-7, N1-8) → N1-9 → N1-10.

## Per-item acceptance (planner correction, 2026-10-04)

The original plan implied every item must reach `--gates 1,2,4,8` all-green. That is
impossible for the early items and would force @verifier into NEEDS_WORK verdicts for
work that is correctly out of scope: gate 2 runs the whole 195-test suite and gate 4's
storm needs `POST /_test/reset`, so neither can pass before N1-2. The planner's error.

A GO on an item means: **gate 1 PASS, gate 8 PASS, no test errors at import, no test
that passed on an earlier item now failing (a per-item ratchet), and every test in the
item's own scope passing.** Gates 2 and 4 become binding as listed below.

| item | gate 1 | gate 2 | gate 4 | gate 8 | item-scope tests that must pass |
|---|---|---|---|---|---|
| N1-1 | PASS | advisory | advisory | PASS | `test_runtime.py`, and the `test_errors_precedence.py` cases not needing a later endpoint |
| N1-2 | PASS | advisory | **PASS** | PASS | + `test_reset_fixture.py`, and `GET /me` (R-1-120) must answer, since gate 4's `invariant()` reads it per user to check conservation — @builder confirmed it by creating `stage-1/service/routes/me.py` in this item |
| N1-3 | PASS | advisory | PASS | PASS | + `test_auth.py` |
| N1-4 | PASS | advisory | PASS | PASS | + `test_idempotency.py` |
| N1-5 | PASS | advisory | PASS | PASS | + `test_payments_activity.py` |
| N1-6 | PASS | advisory | PASS | PASS | + `test_requests.py` |
| N1-7 | PASS | advisory | PASS | PASS | + `test_splits.py` |
| N1-8 | PASS | advisory | PASS | PASS | + `test_settlements.py` |
| N1-9 | PASS | **PASS** | PASS | PASS | + `test_export_import.py` |
| N1-10 | PASS | PASS | PASS | PASS | + `test_concurrency.py`, all 195 |

"advisory" = @verifier records the count as evidence and it does not block the item,
but the ratchet applies: a test green on item N must stay green on item N+1.
Gate 4 is binding from N1-2 because the storm hook only needs reset plus whichever
money paths exist — unimplemented paths return 404, which the hook treats as a legal
outcome; a 5xx or a broken invariant is never legal.

Gate commands per item:

```
/home/prashant/projects/band-work/result/.venv/bin/python -m factory.gates.run stage-1 --node <id> --gates 1,2,4,8
```

Stage close:

```
/home/prashant/projects/band-work/result/.venv/bin/python -m factory.gates.run stage-1 --node close --gates all \
  --scope <last-GO>..HEAD --track pocketful --kickoff /home/prashant/projects/dark-factory-wearedevs
```
