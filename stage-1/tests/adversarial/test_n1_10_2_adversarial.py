"""Adversarial findings against N1-10.2 (the one interleaving target 1
could not reach: a waiter PARKED on an in-flight idempotency claim at the
instant a reset or import wipes the table).

Target 1 (test_n1_10_adversarial.py) used a different idempotency key per
thread, so no thread was ever blocked inside `resolve_or_claim`'s
`event.wait()` when load landed. These tests force that exact
interleaving: a winner holding a claim on a 32-entry POST /settlements,
one or more waiters parked on the SAME key + byte-identical body, and a
reset/import landing while they're parked.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, auth_idem, login_token, make_fixture,  # noqa: E402
                      reset_ok, unique, unique_handle, user)

_REQUEST_BUDGET_S = 5.0


def _multi_settlement_fixture(n_operators, n_recipients=32, per_transfer=1):
    """n_operators independent operators, each with their own n_recipients,
    all seeded in ONE reset (every reset_ok call invalidates every
    previously-issued token, so building them one at a time would wipe
    the earlier ones out from under themselves)."""
    all_users = []
    operators = []
    for k in range(n_operators):
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

    out = []
    for op_id, op_handle, op_email, recipients in operators:
        op_token = login_token(op_email)
        transfers = [{"from_handle": op_handle, "to_handle": handle, "amount": per_transfer}
                     for _, handle, _ in recipients]
        out.append((op_token, transfers))
    return out


def _run_waiter_race_once(wipe_fn, n_waiters=4, n_contenders=8):
    """One trial: start a 32-entry settlement as the winner, park several
    waiters on the identical key + body, fire a wave of OTHER
    distinct-key settlements to add STORE.write_lock() contention, and —
    all synchronized to start at the same instant via a Barrier, to
    maximize the chance the wipe's own write-lock acquisition actually
    lands between the winner's claim and its commit rather than safely
    before or after — land `wipe_fn()`. Returns (responses, wipe_result).

    This is fundamentally a race against a sub-millisecond window with
    no API-level way to widen it further (every write path here is pure
    in-memory Python); a single trial is not strong evidence either way,
    which is why callers run this many times."""
    all_ops = _multi_settlement_fixture(n_operators=1 + n_contenders)
    op_token, transfers = all_ops[0]
    key = unique("parked")

    n_attempts = 1 + n_waiters  # one winner + N waiters, all identical
    n_participants = n_attempts + n_contenders + 1  # + the wipe itself
    barrier = threading.Barrier(n_participants)

    def settle():
        barrier.wait()
        t0 = time.monotonic()
        r = api_post("/settlements", json={"transfers": transfers}, headers=auth_idem(op_token, key))
        return r.status_code, r.text, time.monotonic() - t0

    def contend(job):
        c_token, c_transfers, c_key = job
        barrier.wait()
        try:
            api_post("/settlements", json={"transfers": c_transfers}, headers=auth_idem(c_token, c_key))
        except Exception:
            pass  # a transport hiccup from an unrelated contender is not this test's assertion

    def wipe():
        barrier.wait()
        return wipe_fn()

    contender_jobs = [(tok, trs, unique(f"contend{i}")) for i, (tok, trs) in enumerate(all_ops[1:])]

    with ThreadPoolExecutor(n_participants) as pool:
        futures = [pool.submit(settle) for _ in range(n_attempts)]
        for job in contender_jobs:
            pool.submit(contend, job)
        wipe_future = pool.submit(wipe)
        responses = [f.result(timeout=10.0) for f in futures]
        wipe_result = wipe_future.result(timeout=10.0)

    return responses, wipe_result


def _run_waiter_race(wipe_fn, n_trials=15):
    """Repeat the single-trial race many times — the window is
    sub-millisecond and not reliably forced by black-box HTTP timing
    alone, so a lone trial proves little in either direction. Returns
    the union of every trial's (responses, wipe_result), plus the max
    observed elapsed among all 2nd-through-last identical attempts per
    trial as a proxy for whether genuine parking (not an instant
    replay) was ever actually exercised."""
    all_responses = []
    wipe_results = []
    for _ in range(n_trials):
        responses, wipe_result = _run_waiter_race_once(wipe_fn)
        all_responses.append(responses)
        wipe_results.append(wipe_result)
    return all_responses, wipe_results


def test_reset_landing_while_waiters_are_parked_on_an_in_flight_claim():
    """R-1-080b/R-1-112a: a reset with a DIFFERENT fixture lands while one
    or more callers are parked inside resolve_or_claim's event.wait() for
    the SAME key + body as an in-flight 32-entry settlement. Every
    participant must get a response inside the 5s budget, never a 5xx,
    and either 200 with the winner's exact body or a legitimate error
    from being re-tried as a fresh first use against the now-wiped
    handles (404 — R-1-040: nothing from before the reset is visible)."""

    def do_reset():
        new_uid, new_handle = unique("u"), unique_handle("postwipe")
        new_email = f"{new_handle}@example.com"
        t0 = time.monotonic()
        r = reset_ok(make_fixture([user(new_uid, new_handle, balance=777, email=new_email)]))
        return r.status_code, time.monotonic() - t0, new_email

    all_responses, wipe_results = _run_waiter_race(do_reset)

    max_elapsed_seen = 0.0
    for trial_i, (responses, (reset_status, reset_elapsed, new_email)) in enumerate(zip(all_responses, wipe_results)):
        assert reset_status == 204
        assert reset_elapsed < 10.0, (
            f"R-1-015: reset must finish within 10s even mid-race, took {reset_elapsed:.2f}s (trial {trial_i})"
        )

        over_budget = [(s, e) for s, _, e in responses if e > _REQUEST_BUDGET_S]
        assert not over_budget, (
            f"R-1-015 breach (trial {trial_i}): a parked waiter exceeded {_REQUEST_BUDGET_S}s: {over_budget}"
        )

        bad_5xx = [(s, b[:200]) for s, b, _ in responses if s >= 500]
        assert not bad_5xx, (
            f"R-1-005/R-1-080b breach (trial {trial_i}): a parked waiter got a 5xx when the entry it was "
            f"waiting on was wiped out from under it by a reset: {bad_5xx}"
        )

        statuses = Counter(s for s, _, _ in responses)
        winners = [b for s, b, _ in responses if s == 201]
        assert len(winners) <= 1, f"never two winners even across a reset race (trial {trial_i}): {len(winners)} 201s"
        replays = [b for s, b, _ in responses if s == 200]
        if winners:
            assert all(b == winners[0] for b in replays), f"every 200 must carry the exact winner body (trial {trial_i})"
        for s, b, _ in responses:
            if s not in (200, 201):
                assert 400 <= s < 500, f"unexpected non-4xx/non-2xx status {s} (trial {trial_i}): {b}"
                assert '"error"' in b, f"a {s} response must carry the error envelope (trial {trial_i}): {b}"

        bal_new = api_get("/me", headers={"Authorization": f"Bearer {login_token(new_email)}"}).json()["balance"]
        assert bal_new == 777, f"R-1-001: new fixture's seeded balance must be exact post-race, got {bal_new} (trial {trial_i})"

        max_elapsed_seen = max(max_elapsed_seen, max(e for _, _, e in responses))

    print(f"reset-race: {len(all_responses)} trials, max single-response elapsed {max_elapsed_seen:.4f}s "
          f"(near _MAX_TOTAL_WAIT's old 4.0s bound would indicate genuine parking was exercised)")


def test_import_landing_while_waiters_are_parked_on_an_in_flight_claim():
    """Same race, with POST /_test/import (a different fixture, via the
    export/import round trip) in place of reset — restore() has the same
    R-1-112a obligation as clear() and the same hazard."""

    def do_import():
        new_uid, new_handle = unique("u"), unique_handle("postimp")
        new_email = f"{new_handle}@example.com"
        other_fixture = make_fixture([user(new_uid, new_handle, balance=888, email=new_email)])
        # Build the import document via a real export of a throwaway reset,
        # so it's a genuine export/import document, not a hand-built one.
        reset_ok(other_fixture)
        export_doc = api_get("/_test/export").json()
        t0 = time.monotonic()
        r = api_post("/_test/import", json=export_doc)
        return r.status_code, time.monotonic() - t0, new_email

    all_responses, wipe_results = _run_waiter_race(do_import)

    max_elapsed_seen = 0.0
    for trial_i, (responses, (import_status, import_elapsed, new_email)) in enumerate(zip(all_responses, wipe_results)):
        assert import_status == 204, f"import must succeed (trial {trial_i}): {import_status}"
        assert import_elapsed < 10.0, (
            f"R-1-015: import must finish within 10s even mid-race, took {import_elapsed:.2f}s (trial {trial_i})"
        )

        over_budget = [(s, e) for s, _, e in responses if e > _REQUEST_BUDGET_S]
        assert not over_budget, (
            f"R-1-015 breach (trial {trial_i}): a parked waiter exceeded {_REQUEST_BUDGET_S}s: {over_budget}"
        )

        bad_5xx = [(s, b[:200]) for s, b, _ in responses if s >= 500]
        assert not bad_5xx, (
            f"R-1-005/R-1-080b breach (trial {trial_i}): a parked waiter got a 5xx when the entry it was "
            f"waiting on was wiped out from under it by an import: {bad_5xx}"
        )

        statuses = Counter(s for s, _, _ in responses)
        winners = [b for s, b, _ in responses if s == 201]
        assert len(winners) <= 1, f"never two winners even across an import race (trial {trial_i}): {len(winners)} 201s"
        replays = [b for s, b, _ in responses if s == 200]
        if winners:
            assert all(b == winners[0] for b in replays), f"every 200 must carry the exact winner body (trial {trial_i})"
        for s, b, _ in responses:
            if s not in (200, 201):
                assert 400 <= s < 500, f"unexpected non-4xx/non-2xx status {s} (trial {trial_i}): {b}"
                assert '"error"' in b, f"a {s} response must carry the error envelope (trial {trial_i}): {b}"

        bal_new = api_get("/me", headers={"Authorization": f"Bearer {login_token(new_email)}"}).json()["balance"]
        assert bal_new == 888, f"R-1-001: imported fixture's balance must be exact post-race, got {bal_new} (trial {trial_i})"

        max_elapsed_seen = max(max_elapsed_seen, max(e for _, _, e in responses))

    print(f"import-race: {len(all_responses)} trials, max single-response elapsed {max_elapsed_seen:.4f}s")
