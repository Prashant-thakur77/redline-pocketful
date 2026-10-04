"""Adversarial findings against N1-4 (shared idempotency layer,
`service/idempotency.py`).

No write path (`/payments`, `/requests`, `/requests/{id}/pay`, `/splits`,
`/settlements`) is routed yet — they land in N1-5..8 — so this layer cannot
be driven over HTTP. These tests import `service.idempotency` directly
against the exact module every later write endpoint will use, the same
white-box approach builder's own handoff describes using (a throwaway
`Endpoint` subclass) but did not commit.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

STAGE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(STAGE_DIR))

from service.errors import ApiError  # noqa: E402
from service.idempotency import IdempotencyStore  # noqa: E402


def test_bool_and_int_bodies_are_not_the_same_json_value_r_1_106():
    """R-1-106: '{}' and '{"visibility":"public"}' are different bodies;
    only *numbers* compared by exact numeric value collapse together
    (1000 == 1000.0 == 1e3). A JSON boolean and a JSON number are
    different types and must not collapse the same way.

    `resolve_or_claim`'s "same body" check is `entry.request_body != body`
    on the parsed Python dicts. Python's `==` makes `True == 1` and
    `False == 0`, so `{"flag": 1}` and `{"flag": True}` compare equal even
    though they are different JSON values — a caller can retry with a
    boolean swapped in for an integer (or vice versa) and get a silent
    `200` replay of someone else's request instead of the
    `409 idempotency_key_reuse` R-1-106 requires for a genuinely
    different body.
    """
    store = IdempotencyStore()
    outcome, composite = store.resolve_or_claim("u1", "POST", "/payments", "k1", {"flag": 1})
    assert outcome == "claimed"
    store.commit(composite, 201, {"flag": 1, "result": "ok"})

    try:
        store.resolve_or_claim("u1", "POST", "/payments", "k1", {"flag": True})
    except ApiError as exc:
        assert exc.code == "idempotency_key_reuse", (
            f"expected idempotency_key_reuse for a body that swaps an int for a bool, got {exc.code}"
        )
    else:
        raise AssertionError(
            "a body with {'flag': True} was silently treated as the same request as "
            "{'flag': 1} and replayed instead of raising 409 idempotency_key_reuse"
        )


def test_concurrent_claims_same_key_same_body_exactly_one_runs():
    """R-1-108: for N concurrent identical requests with an unused key,
    exactly one claims and runs the operation; every other caller blocks
    until the winner commits, then replays the identical body — never an
    error, never two winners."""
    store = IdempotencyStore()
    body = {"to_handle": "bob", "amount": 500}
    claims = []
    replays = []
    lock = threading.Lock()
    start = threading.Barrier(20)

    def attempt():
        start.wait()
        outcome, payload = store.resolve_or_claim("u1", "POST", "/payments", "race-key", body)
        if outcome == "claimed":
            with lock:
                claims.append(payload)
            # Simulate the real operation taking a moment, so losers
            # actually have to block rather than find a fast commit.
            threading.Event().wait(0.05)
            store.commit(payload, 201, {"payment_id": "p1"})
        else:
            with lock:
                replays.append(payload)

    threads = [threading.Thread(target=attempt) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(claims) == 1, f"expected exactly one claim, got {len(claims)}: {claims}"
    assert len(replays) == 19, f"expected 19 replays, got {len(replays)}"
    assert all(r == (200, {"payment_id": "p1"}) for r in replays), (
        f"every replay must be the winner's committed body verbatim, got {replays}"
    )
