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

Gate commands per item:

```
/home/prashant/projects/band-work/result/.venv/bin/python -m factory.gates.run stage-1 --node <id> --gates 1,2,4,8
```

Stage close:

```
/home/prashant/projects/band-work/result/.venv/bin/python -m factory.gates.run stage-1 --node close --gates all \
  --scope <last-GO>..HEAD --track pocketful --kickoff /home/prashant/projects/dark-factory-wearedevs
```
