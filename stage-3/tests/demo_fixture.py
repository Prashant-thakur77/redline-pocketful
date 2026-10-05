"""The one shared seeded-demo fixture used by the pytest suite and by
`invariants/hook.py`, so both exercise the same data (stage 2's first screen
must never be empty).

Call `build_demo_fixture()` to get a fresh, independent copy — callers may
mutate the result freely.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

CURRENCY = "EUR"
MINOR_UNITS = 2
PASSWORD = "password123"
AUTHORIZATION_TTL_SECONDS = 600

USERS = [
    {"id": "u-alice", "email": "alice@example.com", "password": PASSWORD,
     "display_name": "Alice Nguyen", "handle": "alice", "balance": 10_000},
    {"id": "u-bob", "email": "bob@example.com", "password": PASSWORD,
     "display_name": "Bob Okafor", "handle": "bob", "balance": 5_000},
    {"id": "u-carol", "email": "carol@example.com", "password": PASSWORD,
     "display_name": "Carol Diaz", "handle": "carol", "balance": 3_000},
    {"id": "u-dave", "email": "dave@example.com", "password": PASSWORD,
     "display_name": "Dave Schmidt", "handle": "dave", "balance": 7_000},
    {"id": "u-erin", "email": "erin@example.com", "password": PASSWORD,
     "display_name": "Erin Kowalski", "handle": "erin", "balance": 2_000},
    {"id": "u-frank", "email": "frank@example.com", "password": PASSWORD,
     "display_name": "Frank Ricci", "handle": "frank", "balance": 1_500},
]

def _payments(now: datetime) -> list[dict]:
    """p-seed-1 and p-seed-2 share the exact same `created_at` instant so a
    test can exercise R-3-019's ascending-id tiebreak when two revisions (or
    two payments) tie on timestamp ordering."""
    shared_instant = (now - timedelta(days=2)).isoformat()
    return [
        {"id": "p-seed-1", "from_user_id": "u-alice", "to_user_id": "u-bob",
         "amount": 500, "note": "lunch", "visibility": "public", "created_at": shared_instant},
        {"id": "p-seed-2", "from_user_id": "u-carol", "to_user_id": "u-dave",
         "amount": 200, "note": "secret gift", "visibility": "private", "created_at": shared_instant},
    ]

REQUESTS = [
    {"id": "r-seed-1", "requester_id": "u-alice", "payer_id": "u-bob",
     "amount": 300, "note": "rent", "status": "pending"},
    {"id": "r-seed-2", "requester_id": "u-carol", "payer_id": "u-dave",
     "amount": 150, "note": "movie tickets", "status": "pending"},
    {"id": "r-seed-3", "requester_id": "u-dave", "payer_id": "u-erin",
     "amount": 100, "note": "old, declined", "status": "declined"},
    {"id": "r-seed-4", "requester_id": "u-erin", "payer_id": "u-frank",
     "amount": 50, "note": "old, cancelled", "status": "cancelled"},
    {"id": "r-seed-5", "requester_id": "u-frank", "payer_id": "u-alice",
     "amount": 400, "note": "old, paid", "status": "paid"},
]

SETTLEMENT_OPERATOR_IDS = ["u-alice"]


def _authorizations(now: datetime) -> list[dict]:
    """alice is the primary demo user: one open outgoing hold, one open
    incoming hold, one captured, one voided, and one seeded `open` whose
    expires_at is already past (R-2-026: reads as expired, holds nothing).
    Expiry times are kept at least an hour from "now" in either direction,
    as R-2-026 requires."""
    far_future = (now + timedelta(hours=2)).isoformat()
    long_past = (now - timedelta(hours=1)).isoformat()
    return [
        {"id": "a-seed-open-out", "from_user_id": "u-alice", "to_user_id": "u-bob",
         "amount": 1000, "note": "hotel hold", "visibility": "public",
         "status": "open", "expires_at": far_future,
         "created_at": (now - timedelta(hours=3)).isoformat()},
        {"id": "a-seed-open-in", "from_user_id": "u-dave", "to_user_id": "u-alice",
         "amount": 800, "note": "deposit", "visibility": "public",
         "status": "open", "expires_at": far_future,
         "created_at": (now - timedelta(hours=4)).isoformat()},
        {"id": "a-seed-captured", "from_user_id": "u-alice", "to_user_id": "u-erin",
         "amount": 500, "note": "settled hold", "visibility": "public",
         "status": "captured", "expires_at": far_future,
         "created_at": (now - timedelta(days=1)).isoformat()},
        {"id": "a-seed-voided", "from_user_id": "u-bob", "to_user_id": "u-alice",
         "amount": 300, "note": "cancelled hold", "visibility": "public",
         "status": "voided", "expires_at": far_future,
         "created_at": (now - timedelta(days=1, hours=1)).isoformat()},
        {"id": "a-seed-expired", "from_user_id": "u-alice", "to_user_id": "u-frank",
         "amount": 600, "note": "lapsed hold", "visibility": "public",
         "status": "open", "expires_at": long_past,
         "created_at": (now - timedelta(days=3)).isoformat()},
    ]


def build_demo_fixture() -> dict:
    now = datetime.now(timezone.utc)
    return {
        "currency": CURRENCY,
        "minor_units": MINOR_UNITS,
        "users": copy.deepcopy(USERS),
        "payments": _payments(now),
        "requests": copy.deepcopy(REQUESTS),
        "settlement_operator_ids": list(SETTLEMENT_OPERATOR_IDS),
        "authorization_ttl_seconds": AUTHORIZATION_TTL_SECONDS,
        "authorizations": _authorizations(now),
    }


def seeded_total() -> int:
    return sum(u["balance"] for u in USERS)


def opening_balances() -> dict[str, int]:
    """Each user's balance before any seeded payment's effect — the seeded
    `balance` field is already the post-payment ending balance (R-1-043), so
    this reverses each seeded payment to get the opening figure a bitemporal
    `as_of` read before the earliest seeded payment must show (R-3-016)."""
    balances = {u["id"]: u["balance"] for u in USERS}
    for p in _payments(datetime.now(timezone.utc)):
        balances[p["from_user_id"]] += p["amount"]
        balances[p["to_user_id"]] -= p["amount"]
    return balances


# alice's expected `held` right after reset: only a-seed-open-out (1000) counts —
# a-seed-expired holds nothing (R-2-026), a-seed-captured/voided are closed, and
# a-seed-open-in is incoming (R-2-004 counts outgoing holds only).
ALICE_SEEDED_HELD = 1000
