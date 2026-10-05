"""Adversarial findings against N1-10 (hardening: concurrency storm, 50 in
flight, reset under load, export atomicity, test-control budget).

This is the attack half of R-1-108/R-1-005/R-1-015/R-1-244/R-1-001/R-1-208
under load; redline's N1-T.8 pins the correctness half as spec tests —
these tests are about timing and reachability, not duplicating that.
"""
from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, auth, auth_idem, login_token, make_fixture,  # noqa: E402
                      reset_ok, unique, unique_handle, user)

_REQUEST_BUDGET_S = 5.0


def _settlement_fixture(n_recipients=32, per_transfer=10):
    op_id, op_handle = unique("u"), unique_handle("op")
    op_email = f"{op_handle}@example.com"
    recipients = []
    for i in range(n_recipients):
        uid, handle = unique("u"), unique_handle(f"r{i}")
        recipients.append((uid, handle, f"{handle}@example.com"))

    users = [user(op_id, op_handle, balance=n_recipients * per_transfer * 2, email=op_email)]
    users += [user(uid, handle, balance=0, email=email) for uid, handle, email in recipients]
    reset_ok(make_fixture(users, settlement_operator_ids=[op_id]))

    op_token = login_token(op_email)
    transfers = [{"from_handle": op_handle, "to_handle": handle, "amount": per_transfer}
                 for _, handle, _ in recipients]
    return op_token, transfers


def test_r_1_108_timing_heaviest_write_many_losers_same_key():
    """Target 1: can a loser waiting on a slow winner hit the idempotency
    layer's internal wait deadline (_MAX_TOTAL_WAIT = 4.0s)? Make the
    winner as slow as the API legitimately allows — a 32-entry
    POST /settlements, the heaviest single write path — and fire up to
    50 byte-identical concurrent requests on one unused key.

    R-1-108 requires exactly one 201 and the rest 200 with the identical
    body. R-1-005 requires no request ever returns 5xx. R-1-060 requires
    every 4xx/5xx body to be the error envelope. A timeout-driven
    RuntimeError inside resolve_or_claim propagates to server.py's
    generic exception handler, which answers 500 internal_error — any
    loser landing there is simultaneously a breach of R-1-108 (wrong
    status/body) and R-1-005 (a 5xx was produced at all).
    """
    key = unique("heaviest")
    results = {}
    lock = threading.Lock()

    for concurrency in (8, 20, 50):
        op_token, transfers = _settlement_fixture(n_recipients=32, per_transfer=1)

        def attempt(_i):
            t0 = time.monotonic()
            r = api_post("/settlements", json={"transfers": transfers}, headers=auth_idem(op_token, key))
            elapsed = time.monotonic() - t0
            return r.status_code, r.text, elapsed

        with ThreadPoolExecutor(concurrency) as pool:
            responses = list(pool.map(attempt, range(concurrency)))

        statuses = Counter(s for s, _, _ in responses)
        max_elapsed = max(e for _, _, e in responses)
        with lock:
            results[concurrency] = (dict(statuses), max_elapsed)

        over_budget = [(s, e) for s, _, e in responses if e > _REQUEST_BUDGET_S]
        assert not over_budget, (
            f"R-1-015 breach at concurrency={concurrency}: {len(over_budget)} response(s) exceeded "
            f"the {_REQUEST_BUDGET_S}s budget: {over_budget}"
        )

        bad = [(s, b[:200]) for s, b, _ in responses if s not in (200, 201)]
        assert not bad, (
            f"R-1-108/R-1-005 breach at concurrency={concurrency}: expected only 200/201, got: {bad}"
        )
        assert statuses.get(201, 0) == 1, (
            f"R-1-108 breach at concurrency={concurrency}: expected exactly one 201, got {dict(statuses)}"
        )
        assert statuses.get(200, 0) == concurrency - 1, (
            f"R-1-108 breach at concurrency={concurrency}: expected {concurrency - 1} replays, "
            f"got {dict(statuses)}"
        )
        bodies = {b for _, b, _ in responses}
        assert len(bodies) == 1, (
            f"R-1-108 breach at concurrency={concurrency}: not every response carried the "
            f"identical winner body, got {len(bodies)} distinct bodies"
        )

    # Report what was actually observed, for the record — this is a HOLDS
    # if every concurrency level above produced the expected 1x201/Nx200
    # split with every response inside budget: the timeout path (4.0s) was
    # never reached because a 32-entry settlement under this storm's
    # thread contention completed in milliseconds, not seconds.
    print(f"R-1-108/R-1-015 timing results by concurrency: {results}")


def test_r_1_108_timing_maximum_global_lock_contention():
    """Target 1, pushed harder: the single real serialization point every
    winner contends on is STORE.write_lock() — one global lock, not one
    per key. So the realistic way to make a winner (and therefore its
    losers) wait longer is many DIFFERENT keys' winners competing for
    that same lock at once, not just many losers on one key. 10 distinct
    32-entry settlements, 50 identical requests each, all 500 requests
    fired at once — all set up in ONE reset, since each POST /_test/reset
    invalidates every token issued before it (R-1-040)."""
    n_keys = 10
    per_key = 50
    n_recipients = 32
    per_transfer = 1

    operators = []
    all_users = []
    for k in range(n_keys):
        op_id, op_handle = unique("u"), unique_handle(f"op{k}")
        op_email = f"{op_handle}@example.com"
        recipients = []
        for i in range(n_recipients):
            uid, handle = unique("u"), unique_handle(f"k{k}r{i}")
            recipients.append((uid, handle, f"{handle}@example.com"))
        all_users.append(user(op_id, op_handle, balance=n_recipients * per_transfer * 2, email=op_email))
        all_users += [user(uid, handle, balance=0, email=email) for uid, handle, email in recipients]
        operators.append((op_id, op_handle, op_email, recipients))

    reset_ok(make_fixture(all_users, settlement_operator_ids=[op_id for op_id, *_ in operators]))

    jobs = []
    for k, (op_id, op_handle, op_email, recipients) in enumerate(operators):
        op_token = login_token(op_email)
        transfers = [{"from_handle": op_handle, "to_handle": handle, "amount": per_transfer}
                     for _, handle, _ in recipients]
        key = unique(f"contend{k}")
        for _ in range(per_key):
            jobs.append((op_token, transfers, key))

    def attempt(job):
        token, transfers, key = job
        t0 = time.monotonic()
        r = api_post("/settlements", json={"transfers": transfers}, headers=auth_idem(token, key))
        return r.status_code, r.text, time.monotonic() - t0

    with ThreadPoolExecutor(len(jobs)) as pool:
        responses = list(pool.map(attempt, jobs))

    over_budget = [e for _, _, e in responses if e > _REQUEST_BUDGET_S]
    assert not over_budget, (
        f"R-1-015 breach under {n_keys}x{per_key}-way global lock contention: "
        f"{len(over_budget)} response(s) exceeded {_REQUEST_BUDGET_S}s, max={max(over_budget, default=None)}"
    )
    bad = [s for s, _, _ in responses if s not in (200, 201)]
    assert not bad, f"R-1-108/R-1-005 breach under max contention: non-200/201 statuses seen: {Counter(bad)}"
    statuses = Counter(s for s, _, _ in responses)
    assert statuses[201] == n_keys, (
        f"expected exactly {n_keys} winners (one per key), got {statuses[201]}: {dict(statuses)}"
    )
    assert statuses[200] == n_keys * (per_key - 1), (
        f"expected {n_keys * (per_key - 1)} replays, got {dict(statuses)}"
    )
    print(f"max contention max elapsed: {max(e for _, _, e in responses):.3f}s over {len(jobs)} requests")


def test_r_1_244_reset_under_load_no_torn_state_and_idempotency_cleared():
    """Target 2: a reset concurrent with other traffic never produces a
    5xx, and after it returns 204 only the new fixture is visible,
    including the idempotency table (R-1-040, R-1-244) — the defect
    @verifier found at b78abac (IDEMPOTENCY.clear() defined but never
    called) is exactly what this guards against regressing to."""
    op_id, op_handle = unique("u"), unique_handle("preop")
    op_email = f"{op_handle}@example.com"
    bob_id, bob_handle = unique("u"), unique_handle("prebob")
    bob_email = f"{bob_handle}@example.com"
    reset_ok(make_fixture([user(op_id, op_handle, balance=10_000, email=op_email),
                            user(bob_id, bob_handle, balance=0, email=bob_email)]))
    old_token = login_token(op_email)

    pre_reset_key = unique("pre-reset-claim")
    r_claim = api_post("/payments", json={"to_handle": bob_handle, "amount": 10},
                        headers=auth_idem(old_token, pre_reset_key))
    assert r_claim.status_code == 201, r_claim.text

    errors = []
    statuses = []
    stop = threading.Event()
    lock = threading.Lock()

    def hammer(i):
        while not stop.is_set():
            try:
                r = api_post("/payments", json={"to_handle": bob_handle, "amount": 1},
                              headers=auth_idem(old_token, unique(f"storm{i}")))
                with lock:
                    statuses.append(r.status_code)
            except Exception as exc:  # transport error during the reset race
                with lock:
                    errors.append(str(exc))

    threads = [threading.Thread(target=hammer, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()

    new_uid, new_handle = unique("u"), unique_handle("newfix")
    new_email = f"{new_handle}@example.com"
    t0 = time.monotonic()
    r_reset = api_post("/_test/reset", json=make_fixture([user(new_uid, new_handle, balance=4242, email=new_email)]))
    reset_elapsed = time.monotonic() - t0

    stop.set()
    for t in threads:
        t.join(timeout=5.0)

    assert r_reset.status_code == 204, f"reset must succeed: {r_reset.status_code} {r_reset.text}"
    assert reset_elapsed < 10.0, f"R-1-015: reset must complete within 10s, took {reset_elapsed:.2f}s"
    assert not errors, f"no transport error allowed on in-flight operations during a reset: {errors}"
    assert all(s < 500 for s in statuses), f"no 5xx allowed on in-flight operations during a reset: {statuses}"

    # Old state is gone.
    r_old_me = api_get("/me", headers=auth(old_token))
    assert r_old_me.status_code == 401, "the old fixture's token must not survive the reset"

    # New state is the only thing visible, and conservation holds on it.
    new_token = login_token(new_email)
    bal_new = api_get("/me", headers=auth(new_token)).json()["balance"]
    assert bal_new == 4242, f"new fixture's balance must be exactly as seeded, got {bal_new}"

    # The pre-reset idempotency claim must not replay after the reset —
    # it must behave as a genuine first use against the NEW state (and
    # 401 immediately since the old token is dead, never a replay of the
    # old payment body).
    r_replay_attempt = api_post("/payments", json={"to_handle": bob_handle, "amount": 10},
                                 headers=auth_idem(old_token, pre_reset_key))
    assert r_replay_attempt.status_code == 401, (
        f"a key claimed before reset must not replay after it (R-1-040): "
        f"got {r_replay_attempt.status_code}: {r_replay_attempt.text}"
    )


def test_r_1_005_50_simultaneous_connections_no_refusals_or_5xx():
    """Target 3: 50 connections opened simultaneously (not ramped). Zero
    connection resets/refusals/transport errors, zero 5xx, every response
    within the 5s budget. Scope limit: correctness is only required up to
    50 in flight; this test probes exactly 50, never more, so any result
    here is reportable as a BREACH if it fails."""
    uid, handle = unique("u"), unique_handle("conn50")
    email = f"{handle}@example.com"
    reset_ok(make_fixture([user(uid, handle, balance=0, email=email)]))
    token = login_token(email)

    errors = []
    results = []
    lock = threading.Lock()

    def attempt(_i):
        try:
            t0 = time.monotonic()
            r = api_get("/me", headers=auth(token))
            elapsed = time.monotonic() - t0
            with lock:
                results.append((r.status_code, elapsed))
        except Exception as exc:
            with lock:
                errors.append(str(exc))

    barrier_threads = []
    start_barrier = threading.Barrier(50)

    def attempt_synced(i):
        start_barrier.wait()
        attempt(i)

    for i in range(50):
        barrier_threads.append(threading.Thread(target=attempt_synced, args=(i,)))
    for t in barrier_threads:
        t.start()
    for t in barrier_threads:
        t.join(timeout=10.0)

    assert not errors, f"no transport error allowed at 50 simultaneous connections: {errors}"
    assert len(results) == 50, f"every one of the 50 connections must get a response, got {len(results)}"
    bad_status = [s for s, _ in results if s >= 500]
    assert not bad_status, f"no 5xx allowed at 50 simultaneous connections: {bad_status}"
    over_budget = [e for _, e in results if e > _REQUEST_BUDGET_S]
    assert not over_budget, f"every response must be within {_REQUEST_BUDGET_S}s: {over_budget}"


def test_r_1_208_export_internally_consistent_under_concurrent_storm():
    """Target 4: export while a storm of payments is landing, repeatedly.
    Every exported document must be internally consistent (balances sum
    to the seeded total, every payment references users present in the
    document) and export itself must change no state. Then import a
    mid-storm export into a freshly reset service and check conservation
    holds there too."""
    uid_a, h_a = unique("u"), unique_handle("exla")
    uid_b, h_b = unique("u"), unique_handle("exlb")
    email_a, email_b = f"{h_a}@example.com", f"{h_b}@example.com"
    total = 10_000
    reset_ok(make_fixture([user(uid_a, h_a, balance=total, email=email_a),
                            user(uid_b, h_b, balance=0, email=email_b)]))
    token_a = login_token(email_a)

    snapshots = []
    stop = threading.Event()

    def exporter():
        while not stop.is_set():
            r = api_get("/_test/export")
            if r.status_code == 200:
                snapshots.append(r.json())

    t = threading.Thread(target=exporter)
    t.start()

    for i in range(30):
        r = api_post("/payments", json={"to_handle": h_b, "amount": 5},
                      headers=auth_idem(token_a, unique(f"exstorm{i}")))
        assert r.status_code == 201, r.text

    stop.set()
    t.join(timeout=5.0)

    assert snapshots, "the exporter must have captured at least one snapshot during the storm"

    user_ids_by_snapshot = []
    bad_balance_sums = []
    bad_payment_refs = []
    for doc in snapshots:
        state = doc["state"]
        wallet_sum = sum(state["wallets"].values())
        if wallet_sum != total:
            bad_balance_sums.append(wallet_sum)
        user_ids = {u["id"] for u in state["users"]}
        for p in state["payments"]:
            if p["from_user_id"] not in user_ids or p["to_user_id"] not in user_ids:
                bad_payment_refs.append(p["id"])
        user_ids_by_snapshot.append(user_ids)

    assert not bad_balance_sums, f"a torn export's wallet sum didn't match the seeded total: {bad_balance_sums}"
    assert not bad_payment_refs, f"a torn export referenced a user id not present in itself: {bad_payment_refs}"

    # Export changed no state: conservation still holds on the live service.
    bal_a = api_get("/me", headers=auth(token_a)).json()["balance"]
    bal_b = api_get("/me", headers=auth(login_token(email_b))).json()["balance"]
    assert bal_a + bal_b == total, f"export must change no state: {bal_a} + {bal_b} != {total}"

    # Import the LAST captured mid-storm export into a fresh service and
    # check conservation holds there too.
    last = snapshots[-1]
    reset_ok(make_fixture([user(unique("u"), unique_handle("wipe"), balance=0, email=unique_handle("wipe") + "@example.com")]))
    r_import = api_post("/_test/import", json=last)
    assert r_import.status_code == 204, r_import.text
    imported_sum = sum(last["state"]["wallets"].values())
    # Re-derive total from the imported document itself (it may reflect
    # a different point in the storm than `total` above).
    live_sum = 0
    for u in last["state"]["users"]:
        tok = login_token(u["email"], "password123")
        live_sum += api_get("/me", headers=auth(tok)).json()["balance"]
    assert live_sum == imported_sum, (
        f"conservation must hold on the imported mid-storm snapshot: {live_sum} != {imported_sum}"
    )


def test_r_1_015_moderate_fixture_reset_export_import_under_10s():
    """Target 5: a moderately large fixture (200 users, 500 payments)
    must reset within 10s, and export/import of that state must each
    come in under 10s too. Moderate, not adversarially huge — a timeout
    on an absurd fixture size is explicitly out of scope."""
    n_users = 200
    users = []
    ids = []
    for i in range(n_users):
        uid, handle = unique("u"), unique_handle(f"big{i}")
        ids.append(uid)
        users.append(user(uid, handle, balance=1000, email=f"{handle}@example.com"))

    payments = []
    for i in range(500):
        frm, to = ids[i % n_users], ids[(i + 1) % n_users]
        payments.append({"id": unique("bigp"), "from_user_id": frm, "to_user_id": to,
                          "amount": 1, "note": "", "visibility": "public"})

    fixture = make_fixture(users, payments=payments)

    t0 = time.monotonic()
    r_reset = reset_ok(fixture)
    reset_elapsed = time.monotonic() - t0
    assert reset_elapsed < 10.0, f"reset of a 200-user/500-payment fixture took {reset_elapsed:.2f}s"

    t0 = time.monotonic()
    r_export = api_get("/_test/export")
    export_elapsed = time.monotonic() - t0
    assert r_export.status_code == 200, r_export.text
    assert export_elapsed < 10.0, f"export of that state took {export_elapsed:.2f}s"

    t0 = time.monotonic()
    r_import = api_post("/_test/import", json=r_export.json())
    import_elapsed = time.monotonic() - t0
    assert r_import.status_code == 204, r_import.text
    assert import_elapsed < 10.0, f"import of that state took {import_elapsed:.2f}s"
