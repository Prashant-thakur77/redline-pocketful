"""Narrow kills for gate-6 mutation survivors found at the stage-3 close,
log `evidence/gates/s3/close-g6-20261005T142212-97f3.log`.

Each test below names the mutant it targets by reading the LOG's own
per-mutant diff lines, not the dispatch's paraphrase of them — two of the
six paraphrases (mutants #4 and #7) described a different branch/boundary
than what the log actually shows, caught by reading the log directly before
writing the test. The docstrings below state the real line and real mutant.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone

import httpx

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       n_user_fixture, open_authorization, reset_ok, two_user_fixture, unique,
                       unique_handle, url, user)


def test_requests_status_filter_excludes_other_statuses_g6_1():
    """g6 #1 service/routes/requests_read.py:63 [ne to eq]:
    `if status is not None and r["status"] != status: continue` flipped to
    `==` keeps only the requests that do NOT match the filter. The existing
    R-1-165 test only checks the inclusion side on one status (`declined`)
    via `all(x["status"] == "declined" ...)`, which a flipped filter still
    happens to satisfy by accident on that slice. Kill with exact set
    equality against all four statuses from one fixture where the caller is
    party to one request of each. (R-1-163, R-1-165)"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=1000)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])

    pending = api_post("/requests", json={"payer_handle": b_handle, "amount": 1},
                       headers={**auth(token_a), **idem(unique("k"))})
    assert pending.status_code == 201, pending.text
    pending_id = pending.json()["request_id"]

    to_be_paid = api_post("/requests", json={"payer_handle": b_handle, "amount": 1},
                          headers={**auth(token_a), **idem(unique("k"))})
    assert to_be_paid.status_code == 201, to_be_paid.text
    paid_id = to_be_paid.json()["request_id"]
    pay_r = api_post(f"/requests/{paid_id}/pay", json={}, headers={**auth(token_b), **idem(unique("k"))})
    assert pay_r.status_code == 201, pay_r.text

    to_decline = api_post("/requests", json={"payer_handle": b_handle, "amount": 1},
                          headers={**auth(token_a), **idem(unique("k"))})
    assert to_decline.status_code == 201, to_decline.text
    declined_id = to_decline.json()["request_id"]
    decl = api_post(f"/requests/{declined_id}/decline", json={}, headers=auth(token_b))
    assert decl.status_code == 200, decl.text

    to_cancel = api_post("/requests", json={"payer_handle": b_handle, "amount": 1},
                         headers={**auth(token_a), **idem(unique("k"))})
    assert to_cancel.status_code == 201, to_cancel.text
    cancelled_id = to_cancel.json()["request_id"]
    canc = api_post(f"/requests/{cancelled_id}/cancel", json={}, headers=auth(token_a))
    assert canc.status_code == 200, canc.text

    expected_by_status = {
        "pending": {pending_id},
        "paid": {paid_id},
        "declined": {declined_id},
        "cancelled": {cancelled_id},
    }
    for status, expected_ids in expected_by_status.items():
        got = api_get("/requests", headers=auth(token_a), params={"status": status, "limit": 200})
        assert got.status_code == 200, got.text
        got_ids = {r["request_id"] for r in got.json()["requests"]}
        assert got_ids == expected_ids, f"status={status}: expected exactly {expected_ids}, got {got_ids}"

    unfiltered = api_get("/requests", headers=auth(token_a), params={"limit": 200})
    assert unfiltered.status_code == 200, unfiltered.text
    all_ids = {r["request_id"] for r in unfiltered.json()["requests"]}
    assert all_ids == {pending_id, paid_id, declined_id, cancelled_id}


def test_capture_body_equality_identical_and_different_booleans_g6_4():
    """g6 #4 service/idempotency.py:44 [eq to ne]: the mutant is in the
    BOOLEAN branch of json_equal, not the numeric branch —
    `return isinstance(a, bool) and isinstance(b, bool) and a == b` flipped
    to `a != b`. An existing test (test_capture_body_equality_is_type_strict_on_final)
    compares `False` vs `0`, which never even enters this branch since `0`
    is not a bool in Python/JSON terms, so it cannot kill this mutant. Kill
    with two REAL booleans in the one field the ten idempotent write paths
    actually carry one on, capture's `final`: identical booleans
    (true, true) must still replay as 200 (the mutant would wrongly 409
    it), and genuinely different booleans (true vs false) under one key
    must still 409 (the mutant would wrongly return the first receipt).
    (R-1-106)"""
    fixture, ids, handles, tokens = n_user_fixture(2)

    auth_obj1 = open_authorization(tokens[0], handles[1], amount=1000)
    aid1 = auth_obj1["authorization_id"]
    key1 = unique("k")
    first = api_post(f"/authorizations/{aid1}/capture", json={"amount": 100, "final": True},
                     headers={**auth(tokens[1]), **idem(key1)})
    assert first.status_code == 201, first.text
    replay = api_post(f"/authorizations/{aid1}/capture", json={"amount": 100, "final": True},
                      headers={**auth(tokens[1]), **idem(key1)})
    assert replay.status_code == 200, \
        f"identical booleans (true, true) must replay as 200, got {replay.status_code}: {replay.text}"
    assert replay.json() == first.json()

    auth_obj2 = open_authorization(tokens[0], handles[1], amount=1000)
    aid2 = auth_obj2["authorization_id"]
    key2 = unique("k")
    first2 = api_post(f"/authorizations/{aid2}/capture", json={"amount": 100, "final": False},
                      headers={**auth(tokens[1]), **idem(key2)})
    assert first2.status_code == 201, first2.text
    different = api_post(f"/authorizations/{aid2}/capture", json={"amount": 100, "final": True},
                         headers={**auth(tokens[1]), **idem(key2)})
    assert_error(different, 409, "idempotency_key_reuse")


def test_statement_from_boundary_is_inclusive_g6_7():
    """g6 #7 service/routes/statement.py:123 [cmp < to <=]: the mutant is on
    the LOWER (`from`) bound, not the upper one —
    `if from_epoch is not None and effective_epoch < from_epoch: continue`
    flipped to `<=` wrongly excludes a payment effective EXACTLY at `from`,
    which the half-open `[from, to)` window must include. Kill: a statement
    queried with `from` set to exactly a payment's own effective_at must
    still list that payment. (R-3-030, R-3-032)"""
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]
    effective_at = pay.json()["created_at"]

    at_from = api_get("/statement", headers=auth(token_a), params={"from": effective_at, "limit": 50})
    assert at_from.status_code == 200, at_from.text
    ids = [e["payment_id"] for e in at_from.json()["entries"]]
    assert pay_id in ids, \
        f"a payment effective exactly at 'from' must be included (inclusive lower bound): {ids}"


def test_as_of_exact_value_with_asymmetric_sent_and_received_g6_8():
    """g6 #8 service/revisions.py:158 [add-assign to sub]:
    `total += -rev["amount"] if is_from else rev["amount"]` flipped to `-=`
    negates the historical-balance walk's net effect. A sign error only
    shows up if the net is not symmetric, so: a nonzero opening balance,
    one payment sent and one received before `as_of`, all three numbers
    distinct — opening 10000, sent 500, received 1200, expected 10700 —
    whose mutated value (10000 - (-500) - 1200 = 9300 under the flipped
    walk) cannot be produced by a rounding or ordering slip. (R-3-020,
    R-3-021)"""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=10_000), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=2000)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_c = login_token(fixture["users"][2]["email"])

    sent = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert sent.status_code == 201, sent.text

    received = api_post("/payments", json={"to_handle": a_handle, "amount": 1200},
                        headers={**auth(token_c), **idem(unique("k"))})
    assert received.status_code == 201, received.text

    as_of = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    view = api_get("/me", headers=auth(token_a), params={"as_of": as_of})
    assert view.status_code == 200, view.text
    assert view.json()["balance"] == 10_700, \
        f"expected 10000-500+1200=10700, got {view.json()['balance']} (mutated walk would give 9300)"


_RACE_PAIRS = 12
_RACE_ROUNDS = 4
_RACE_TIMEOUT = 6.0


def _race_identical_writes_against(control_path: str) -> list[str]:
    """Fire a burst of identical same-key payment requests (one claims the
    key, the rest park waiting on its completion event) while a concurrent
    control call hits `control_path`. Returns a list of problems (hangs,
    transport errors, 5xx) — empty means clean."""
    errors: list[str] = []
    lock = threading.Lock()

    for round_i in range(_RACE_ROUNDS):
        fixture, token_a, _ = two_user_fixture(balance_a=1_000_000, balance_b=0)
        b_handle = fixture["users"][1]["handle"]
        key = unique("race")
        body = {"to_handle": b_handle, "amount": 1}
        statuses: list[int] = []

        def write():
            try:
                r = httpx.post(url("/payments"), json=body, headers={**auth(token_a), **idem(key)},
                               timeout=_RACE_TIMEOUT)
                with lock:
                    statuses.append(r.status_code)
            except Exception as exc:
                with lock:
                    errors.append(f"round {round_i}: write {type(exc).__name__}: {exc}")

        def control():
            try:
                if control_path == "/_test/reset":
                    httpx.post(url("/_test/reset"), json=fixture, timeout=_RACE_TIMEOUT)
                else:
                    export = httpx.get(url("/_test/export"), timeout=_RACE_TIMEOUT).json()
                    httpx.post(url("/_test/import"), json=export, timeout=_RACE_TIMEOUT)
            except Exception as exc:
                with lock:
                    errors.append(f"round {round_i}: control {type(exc).__name__}: {exc}")

        threads = [threading.Thread(target=write) for _ in range(_RACE_PAIRS)]
        ctrl = threading.Thread(target=control)
        for t in threads:
            t.start()
        ctrl.start()
        for t in threads:
            t.join(timeout=_RACE_TIMEOUT + 2)
            if t.is_alive():
                with lock:
                    errors.append(f"round {round_i}: a write thread did not finish within its own timeout budget")
        ctrl.join(timeout=_RACE_TIMEOUT + 2)
        if ctrl.is_alive():
            errors.append(f"round {round_i}: the control thread did not finish within its own timeout budget")

        if any(s >= 500 for s in statuses):
            errors.append(f"round {round_i}: 5xx observed: {statuses}")

    return errors


def test_reset_concurrent_with_parked_identical_writes_g6_5():
    """g6 #5 service/idempotency.py:140 [drop lock]: `with self._lock:`
    around `clear()`'s wake-and-drop of in-flight entries, dropped to
    `if True:`, lets `clear()` iterate `_entries` while a concurrent claim
    mutates it (R-1-112a). Kill: a burst of identical same-key writes (one
    claims, the rest park on its completion event) racing a concurrent
    `POST /_test/reset`, repeated across several rounds — no hang, no
    transport error, no 5xx, every call inside its own timeout budget.
    (R-1-005, R-1-244, R-1-112a)

    Probabilistic by nature (named as such in the dispatch): if this ever
    flickers, it is dropped and the survivor is accepted rather than kept
    as a flaky gate — judged empirically before commit, not assumed."""
    errors = _race_identical_writes_against("/_test/reset")
    assert not errors, f"hang, transport error or 5xx under concurrent reset: {errors}"


def test_import_concurrent_with_parked_identical_writes_g6_9():
    """g6 #9 service/idempotency.py:159 [ne to eq]: `restore()`'s
    `if entry.state != "complete":` (deciding which parked entries to wake
    rather than silently drop) flipped to `==` wakes the COMPLETED entries
    and abandons the in-flight ones, so a parked duplicate-key caller waits
    on an event nothing will ever set. Kill: the same identical-write burst
    as g6_5, racing a concurrent `POST /_test/import` instead of reset.
    (R-1-005, R-1-244, R-1-112a)

    Also probabilistic; dropped rather than kept flaky, same as g6_5."""
    errors = _race_identical_writes_against("/_test/import")
    assert not errors, f"hang, transport error or 5xx under concurrent import: {errors}"
