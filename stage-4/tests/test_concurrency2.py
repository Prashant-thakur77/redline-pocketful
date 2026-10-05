"""Stage-2 concurrency: R-2-180..184."""
from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from conftest import (api_get, api_post, auth, idem, n_user_fixture, open_authorization, unique)


def test_two_concurrent_full_captures_different_keys_exactly_one_wins():
    """R-2-181"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=500)
    aid = auth_obj["authorization_id"]

    results = []
    lock = threading.Lock()

    def capture(key_suffix):
        r = api_post(f"/authorizations/{aid}/capture", json={},
                     headers={**auth(tokens[1]), **idem(unique(key_suffix))})
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=capture, args=(f"key-{i}",)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    counts = Counter(results)
    assert counts[201] == 1, f"expected exactly one 201, got {dict(counts)}"
    assert counts[409] == 1, f"expected exactly one 409, got {dict(counts)}"

    payer = api_get("/me", headers=auth(tokens[0])).json()
    assert payer["total"] == 500
    assert payer["held"] == 0


def test_capture_racing_void_exactly_one_winner_hold_released_once():
    """R-2-182"""
    fixture, ids, handles, tokens = n_user_fixture(2, balance=1000)
    auth_obj = open_authorization(tokens[0], handles[1], amount=400)
    aid = auth_obj["authorization_id"]

    results = []
    lock = threading.Lock()

    def capture():
        r = api_post(f"/authorizations/{aid}/capture", json={},
                     headers={**auth(tokens[1]), **idem(unique("cap"))})
        with lock:
            results.append(("capture", r.status_code))

    def void():
        r = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[0]))
        with lock:
            results.append(("void", r.status_code))

    t1, t2 = threading.Thread(target=capture), threading.Thread(target=void)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for kind, r in results if r in (200, 201)]
    assert len(successes) == 1, f"exactly one of capture/void must win: {results}"

    payer = api_get("/me", headers=auth(tokens[0])).json()
    receiver = api_get("/me", headers=auth(tokens[1])).json()
    assert payer["held"] == 0
    assert payer["total"] + receiver["total"] == 2000, "total must be conserved regardless of which op won"


def test_payment_racing_authorization_cannot_both_exceed_available():
    """R-2-183"""
    fixture, ids, handles, tokens = n_user_fixture(3, balance=1000)
    results = []
    lock = threading.Lock()

    def pay():
        r = api_post("/payments", json={"to_handle": handles[1], "amount": 700},
                     headers={**auth(tokens[0]), **idem(unique("pay"))})
        with lock:
            results.append(("pay", r.status_code))

    def authorize():
        r = api_post("/authorizations", json={"to_handle": handles[2], "amount": 700},
                     headers={**auth(tokens[0]), **idem(unique("authz"))})
        with lock:
            results.append(("authorize", r.status_code))

    t1, t2 = threading.Thread(target=pay), threading.Thread(target=authorize)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    successes = [r for kind, r in results if r in (200, 201)]
    assert len(successes) <= 1, f"both a 700 payment and a 700 authorization must not both succeed from a 1000 wallet: {results}"
    payer = api_get("/me", headers=auth(tokens[0])).json()
    assert payer["available"] >= 0


def test_storm_mix_holds_r2_001_through_005():
    """R-2-184: a smaller, pytest-level storm mixing payments, authorizations,
    captures and voids with replays; checks R-2-001..005 after the pool
    drains (the full 1000+ op version with mixed status assertions lives in
    invariants/hook.py, driven by gate 4)."""
    fixture, ids, handles, tokens = n_user_fixture(6, balance=2000)
    seeded_total = 2000 * 6
    n = len(handles)

    created_auth_ids = [None] * 40

    def op(i):
        payer_idx = i % n
        other_idx = (i + 1) % n
        key = f"storm2-{i}"
        kind = i % 4
        if kind == 0:
            r = api_post("/payments", json={"to_handle": handles[other_idx], "amount": 1 + (i % 20)},
                         headers={**auth(tokens[payer_idx]), **idem(key)})
            return r.status_code
        if kind == 1:
            r = api_post("/authorizations", json={"to_handle": handles[other_idx], "amount": 1 + (i % 15)},
                         headers={**auth(tokens[payer_idx]), **idem(key)})
            if r.status_code == 201:
                created_auth_ids[i % 40] = (r.json()["authorization_id"], other_idx)
            return r.status_code
        if kind == 2:
            target = created_auth_ids[i % 40]
            if target is None:
                return 404
            aid, receiver_idx = target
            r = api_post(f"/authorizations/{aid}/capture", json={},
                         headers={**auth(tokens[receiver_idx]), **idem(key)})
            return r.status_code
        target = created_auth_ids[(i + 1) % 40]
        if target is None:
            return 404
        aid, _ = target
        r = api_post(f"/authorizations/{aid}/void", json={}, headers=auth(tokens[payer_idx]))
        return r.status_code

    n_ops = 200
    plan = list(range(n_ops)) + list(range(int(n_ops * 0.3)))
    with ThreadPoolExecutor(20) as pool:
        statuses = list(pool.map(op, plan))

    assert all(s < 500 for s in statuses), f"5xx seen: {Counter(statuses)}"

    total_sum = 0
    for token in tokens:
        me = api_get("/me", headers=auth(token)).json()
        assert me["balance"] >= 0
        assert me["available"] >= 0
        assert me["available"] == me["total"] - me["held"]
        total_sum += me["total"]
    assert total_sum == seeded_total, "R-2-001: holds move no money"
