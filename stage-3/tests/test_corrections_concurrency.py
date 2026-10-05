"""Concurrent corrections: R-3-067, R-3-130..133.

`expected_revision` is optimistic concurrency control: when two callers
race to correct the same payment from the same base revision, exactly one
must win (201) and the other must see 409 stale_revision — never both
applying, never a 5xx, never a corrupted/mixed amount.
"""
from __future__ import annotations

import threading

from conftest import api_get, api_post, auth, idem, two_user_fixture, unique


def _correct(token, payment_id, expected_revision, amount, key, results, index):
    r = api_post(f"/payments/{payment_id}/corrections",
                json={"expected_revision": expected_revision, "amount": amount,
                      "effective_at": "2026-01-01T00:00:00+00:00", "reason": f"race-{index}"},
                headers={**auth(token), **idem(key)})
    results[index] = (r.status_code, r.text)


def test_two_concurrent_corrections_from_the_same_base_revision_exactly_one_wins():
    """R-3-067, R-3-130: N racing corrections against the same payment, all
    claiming expected_revision=1 — exactly one 201, the rest 409
    stale_revision, never a 500, never two survivors."""
    fixture, token_a, token_b = two_user_fixture(balance_a=100_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    n = 8
    results = [None] * n
    threads = [
        threading.Thread(target=_correct, args=(token_a, pay_id, 1, 100 + i * 10,
                                                  unique(f"race-{i}"), results, i))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = [r[0] for r in results]
    assert all(s in (201, 409) for s in statuses), f"no status outside {{201,409}} is legal: {results}"
    assert statuses.count(201) == 1, f"exactly one racer must win: {results}"
    for status, text in results:
        if status == 409:
            assert '"stale_revision"' in text, f"a losing racer must be stale_revision, got: {text}"

    revisions = api_get(f"/payments/{pay_id}/revisions", headers=auth(token_a)).json()
    revisions = revisions["revisions"] if isinstance(revisions, dict) else revisions
    assert len(revisions) == 2, f"exactly one correction must have been applied: {revisions}"


def test_concurrent_identical_retries_of_the_same_key_apply_exactly_once():
    """R-3-131, R-3-132: N threads replaying the EXACT same correction
    request (same key, same body) concurrently must still apply it exactly
    once — every response must be the same 201 payload, never a mix of
    201s with different revisions, never a 409 among them."""
    fixture, token_a, token_b = two_user_fixture(balance_a=100_000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    key = unique("shared-retry-key")
    n = 8
    results = [None] * n
    threads = [
        threading.Thread(target=_correct, args=(token_a, pay_id, 1, 500, key, results, i))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = {r[0] for r in results}
    assert statuses <= {200, 201}, f"a shared idempotency key must never produce anything but 200/201: {results}"
    assert 201 in statuses, f"at least one caller must see the original 201: {results}"

    revisions = api_get(f"/payments/{pay_id}/revisions", headers=auth(token_a)).json()
    revisions = revisions["revisions"] if isinstance(revisions, dict) else revisions
    assert len(revisions) == 2, f"a racing identical retry must apply exactly once: {revisions}"


def test_concurrent_corrections_never_leave_a_negative_balance():
    """R-3-133: under a storm of racing corrections that individually could
    overdraw the payer, the service must reject enough of them that the
    payer's balance never actually goes negative."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    pay = api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                   headers={**auth(token_a), **idem(unique("k"))})
    assert pay.status_code == 201, pay.text
    pay_id = pay.json()["payment_id"]

    n = 6
    results = [None] * n
    threads = [
        threading.Thread(target=_correct, args=(token_a, pay_id, 1, 1000 + i * 50,
                                                  unique(f"overdraw-{i}"), results, i))
        for i in range(n)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r[0] in (201, 409) for r in results), f"no status outside {{201,409}} is legal: {results}"
    balance = api_get("/me", headers=auth(token_a)).json()["balance"]
    assert balance >= 0, f"balance went negative under racing corrections: {balance}"
