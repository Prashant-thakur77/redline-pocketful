"""The one shared seeded-demo fixture used by the pytest suite and by
`invariants/hook.py`, so both exercise the same data (stage 2's first screen
must never be empty).

Call `build_demo_fixture()` to get a fresh, independent copy — callers may
mutate the result freely.
"""
from __future__ import annotations

import copy

CURRENCY = "EUR"
MINOR_UNITS = 2
PASSWORD = "password123"

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

PAYMENTS = [
    {"id": "p-seed-1", "from_user_id": "u-alice", "to_user_id": "u-bob",
     "amount": 500, "note": "lunch", "visibility": "public"},
    {"id": "p-seed-2", "from_user_id": "u-carol", "to_user_id": "u-dave",
     "amount": 200, "note": "secret gift", "visibility": "private"},
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


def build_demo_fixture() -> dict:
    return {
        "currency": CURRENCY,
        "minor_units": MINOR_UNITS,
        "users": copy.deepcopy(USERS),
        "payments": copy.deepcopy(PAYMENTS),
        "requests": copy.deepcopy(REQUESTS),
        "settlement_operator_ids": list(SETTLEMENT_OPERATOR_IDS),
    }


def seeded_total() -> int:
    return sum(u["balance"] for u in USERS)
