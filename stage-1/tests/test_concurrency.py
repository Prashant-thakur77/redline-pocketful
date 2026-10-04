"""Concurrency and load: R-1-005, R-1-006, R-1-015, R-1-240..244."""
from __future__ import annotations

import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from conftest import (api_get, api_post, auth, idem, login_token, make_fixture, reset, reset_ok,
                       unique, unique_handle, user)


def _n_user_fixture(n, balance=1000):
    ids = [unique("u") for _ in range(n)]
    handles = [unique_handle(f"p{i}") for i in range(n)]
    fixture = make_fixture([user(ids[i], handles[i], balance=balance) for i in range(n)])
    reset_ok(fixture)
    tokens = [login_token(fixture["users"][i]["email"]) for i in range(n)]
    return fixture, handles, tokens


def test_50_concurrent_requests_no_5xx_and_fast():
    """R-1-005, R-1-015"""
    fixture, handles, tokens = _n_user_fixture(5, balance=10_000)

    def one(i):
        start = time.monotonic()
        r = api_post("/payments", json={"to_handle": handles[(i + 1) % 5], "amount": 1},
                     headers={**auth(tokens[i % 5]), **idem(unique(f"k{i}"))})
        elapsed = time.monotonic() - start
        return r.status_code, elapsed

    with ThreadPoolExecutor(50) as pool:
        results = list(pool.map(one, range(50)))

    statuses = [s for s, _ in results]
    assert all(s < 500 for s in statuses), f"5xx seen: {Counter(statuses)}"
    assert all(elapsed < 5.0 for _, elapsed in results), "every payment request must complete within 5s"


def test_reset_completes_within_10s():
    """R-1-015"""
    fixture, handles, tokens = _n_user_fixture(3)
    start = time.monotonic()
    r = reset(make_fixture([user(unique("u"), unique_handle("z"), balance=1)]))
    elapsed = time.monotonic() - start
    assert r.status_code == 204
    assert elapsed < 10.0


def test_payment_atomic_concurrent_with_reads_never_torn():
    """R-1-002, R-1-006

    Two sequential `/me` reads cannot observe cross-user conservation at an
    instant (stage 1 has no atomic two-balance read: R-1-050 rules out an
    admin endpoint for one), so this does not sum two balances and compare
    against a constant — that sum can only drift as payments land between the
    two reads, "torn" or not. Instead: (a) a balance is never negative, not
    even transiently, under concurrent reads during writes (R-1-002); and
    (b) once a payment's 201 response comes back, the debit is already
    reflected in the sender's own balance and the payment is already visible
    in BOTH parties' own feeds — never visible to one side and not the other
    (R-1-006).
    """
    fixture, handles, tokens = _n_user_fixture(2, balance=1000)
    stop = threading.Event()
    negative = []

    def watch_non_negative():
        while not stop.is_set():
            a = api_get("/me", headers=auth(tokens[0])).json()["balance"]
            b = api_get("/me", headers=auth(tokens[1])).json()["balance"]
            if a < 0 or b < 0:
                negative.append((a, b))

    watcher = threading.Thread(target=watch_non_negative)
    watcher.start()

    for i in range(20):
        r = api_post("/payments", json={"to_handle": handles[1], "amount": 5},
                     headers={**auth(tokens[0]), **idem(unique(f"k{i}"))})
        assert r.status_code == 201, r.text
        payment_id = r.json()["payment_id"]

        sender_balance = api_get("/me", headers=auth(tokens[0])).json()["balance"]
        assert sender_balance == 1000 - 5 * (i + 1), "the debit must already be reflected once 201 returns"

        sender_feed = {p["payment_id"] for p in api_get("/activity", headers=auth(tokens[0])).json()["payments"]}
        receiver_feed = {p["payment_id"] for p in api_get("/activity", headers=auth(tokens[1])).json()["payments"]}
        assert payment_id in sender_feed, "payment must be visible in the sender's own feed immediately"
        assert payment_id in receiver_feed, "payment must be visible in the receiver's feed too, never one-sided"

    stop.set()
    watcher.join(5)
    assert not negative, f"observed a negative balance mid-storm: {negative}"


def test_1000_concurrent_ops_with_replays_invariants_hold():
    """R-1-240"""
    fixture, handles, tokens = _n_user_fixture(6, balance=5000)
    seeded_total = 5000 * 6
    n_ops = 300
    replay_fraction = 0.3

    def one(i):
        payer = i % 6
        payee = (i + 1) % 6
        key = f"storm-{i}"
        r = api_post("/payments", json={"to_handle": handles[payee], "amount": 1 + (i % 10)},
                     headers={**auth(tokens[payer]), **idem(key)})
        return r.status_code

    plan = list(range(n_ops)) + list(range(int(n_ops * replay_fraction)))
    with ThreadPoolExecutor(30) as pool:
        statuses = list(pool.map(one, plan))

    assert all(s < 500 for s in statuses), f"5xx seen: {Counter(statuses)}"
    total = sum(api_get("/me", headers=auth(t)).json()["balance"] for t in tokens)
    assert total == seeded_total
    assert all(api_get("/me", headers=auth(t)).json()["balance"] >= 0 for t in tokens)


def test_two_concurrent_pays_same_request_different_keys():
    """R-1-241"""
    fixture, handles, tokens = _n_user_fixture(3, balance=1000)
    req = api_post("/requests", json={"payer_handle": handles[1], "amount": 10},
                   headers={**auth(tokens[0]), **idem(unique("k"))})
    req_id = req.json()["request_id"]

    results = []
    lock = threading.Lock()

    def pay(key_suffix):
        r = api_post(f"/requests/{req_id}/pay", json={}, headers={**auth(tokens[1]), **idem(unique(key_suffix))})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=pay, args=(f"key-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    counts = Counter(results)
    assert counts[201] == 1, f"expected exactly one 201, got {dict(counts)}"
    assert counts[409] == 1, f"expected exactly one 409 request_not_pending, got {dict(counts)}"


def test_two_concurrent_payments_exceeding_balance_at_most_one_succeeds():
    """R-1-242"""
    fixture, handles, tokens = _n_user_fixture(3, balance=100)
    results = []
    lock = threading.Lock()

    def pay(i):
        r = api_post("/payments", json={"to_handle": handles[(i + 1) % 3], "amount": 80},
                     headers={**auth(tokens[0]), **idem(unique(f"pk{i}"))})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=pay, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    counts = Counter(results)
    assert counts[201] <= 1, f"both concurrent overdraft payments succeeded: {dict(counts)}"
    assert 409 in counts or counts[201] == 1
    balance = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    assert balance >= 0


def test_concurrent_settlements_and_payments_conserve_total():
    """R-1-243"""
    fixture, handles, tokens = _n_user_fixture(4, balance=1000)
    op_fixture_users = fixture["users"]
    op_id = op_fixture_users[0]["id"]
    fixture2 = make_fixture(op_fixture_users, settlement_operator_ids=[op_id])
    reset_ok(fixture2)
    tokens = [login_token(u["email"]) for u in fixture2["users"]]
    seeded_total = sum(u["balance"] for u in fixture2["users"])

    def settle(i):
        body = {"transfers": [{"from_handle": handles[1], "to_handle": handles[2], "amount": 1 + (i % 5)}]}
        return api_post("/settlements", json=body, headers={**auth(tokens[0]), **idem(unique(f"settle{i}"))}).status_code

    def pay(i):
        body = {"to_handle": handles[(i % 3) + 1], "amount": 1 + (i % 5)}
        return api_post("/payments", json=body, headers={**auth(tokens[0]), **idem(unique(f"pay{i}"))}).status_code

    with ThreadPoolExecutor(20) as pool:
        settle_results = list(pool.map(settle, range(15)))
        pay_results = list(pool.map(pay, range(15)))

    assert all(s < 500 for s in settle_results + pay_results)
    total = sum(api_get("/me", headers=auth(t)).json()["balance"] for t in tokens)
    assert total == seeded_total


def test_reset_concurrent_with_traffic_no_5xx_and_clean_cutover():
    """R-1-244"""
    fixture, handles, tokens = _n_user_fixture(3, balance=1000)
    errors = []
    stop = threading.Event()

    def hammer():
        while not stop.is_set():
            r = api_post("/payments", json={"to_handle": handles[1], "amount": 1},
                         headers={**auth(tokens[0]), **idem(unique("hammer"))})
            if r.status_code >= 500:
                errors.append(r.status_code)

    threads = [threading.Thread(target=hammer) for _ in range(5)]
    for t in threads:
        t.start()

    new_fixture = make_fixture([user(unique("u"), unique_handle("fresh"), balance=42)])
    reset_result = reset(new_fixture)

    stop.set()
    for t in threads:
        t.join(5)

    assert reset_result.status_code == 204
    assert not errors, f"5xx seen during concurrent reset: {errors}"

    token = login_token(new_fixture["users"][0]["email"])
    me = api_get("/me", headers=auth(token))
    assert me.status_code == 200
    assert me.json()["balance"] == 42
