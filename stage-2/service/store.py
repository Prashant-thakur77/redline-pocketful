"""In-memory store with a single write lock (R-1-001..006, R-1-016).

State need not survive a restart, so a process-local store guarded by one
lock is the simplest design that gives every money-moving write a single
serialization point: validate everything outside the lock, then take the
lock and do check-and-apply for funds as one atomic step. Later items add
the collections (users, payments, requests, settlements) and the methods
that mutate them; this item only establishes the lock and the reset
generation counter every later write depends on.
"""
from __future__ import annotations

import threading

from .idempotency import IDEMPOTENCY
from .json_utils import now_rfc3339


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self.reset_generation = 0
        self.currency = "EUR"
        self.minor_units = 2
        self.users_by_id: dict[str, dict] = {}
        self.users_by_handle: dict[str, str] = {}  # handle -> user id
        self.users_by_email: dict[str, dict] = {}
        self.wallets: dict[str, int] = {}
        self.payments: dict[str, dict] = {}
        self.requests: dict[str, dict] = {}
        self.settlements: dict[str, dict] = {}
        self.settlement_operator_ids: set[str] = set()
        self.tokens: dict[str, str] = {}  # token -> user_id
        self._next_seq = 0

    def next_seq(self) -> int:
        """Monotonic insertion order, used to break ties for "newest first"
        listings. Must be called with `write_lock()` held."""
        self._next_seq += 1
        return self._next_seq

    def write_lock(self):
        """Context manager: hold this for the whole check-and-apply of a
        money-moving write, never just for the funds check alone."""
        return self._lock

    def apply_reset(self, fields: dict) -> None:
        """Replace all state in one shot (R-1-040). Must be called with
        `write_lock()` already held, so the swap is never observed
        half-done by a concurrent request (R-1-244)."""
        self.reset_generation += 1
        self._next_seq = 0
        seeded_at = now_rfc3339()
        for payment in fields["payments"].values():
            payment["created_at"] = seeded_at
            payment["seq"] = self.next_seq()
        for request in fields["requests"].values():
            request["created_at"] = seeded_at
            request["seq"] = self.next_seq()

        self.currency = fields["currency"]
        self.minor_units = fields["minor_units"]
        self.users_by_id = fields["users"]
        self.users_by_handle = fields["users_by_handle"]
        self.users_by_email = {u["email"]: u for u in fields["users"].values()}
        self.wallets = fields["wallets"]
        self.payments = fields["payments"]
        self.requests = fields["requests"]
        self.settlement_operator_ids = fields["settlement_operator_ids"]
        self.settlements = {}
        self.tokens = {}
        # R-1-040: nothing from before this reset is visible afterwards,
        # including a key claimed or completed under the old fixture — a
        # replay must never resolve against a payment/request that no
        # longer exists (R-1-244: the clear is part of this same atomic
        # swap, under the write lock already held).
        IDEMPOTENCY.clear()

    def apply_import(self, fields: dict) -> None:
        """Replace all state with an imported document (R-1-201/203/205).
        Unlike `apply_reset`, tokens and idempotency records are
        RESTORED, not cleared — R-1-206 requires a retry after import to
        still return the original response, and R-1-205 requires every
        pre-import bearer token to keep working."""
        self.reset_generation += 1
        self._next_seq = fields["next_seq"]
        self.currency = fields["currency"]
        self.minor_units = fields["minor_units"]
        self.users_by_id = fields["users"]
        self.users_by_handle = fields["users_by_handle"]
        self.users_by_email = fields["users_by_email"]
        self.wallets = fields["wallets"]
        self.payments = fields["payments"]
        self.requests = fields["requests"]
        self.settlement_operator_ids = fields["settlement_operator_ids"]
        self.settlements = fields["settlements"]
        self.tokens = fields["tokens"]
        IDEMPOTENCY.restore(fields["idempotency_records"])


STORE = Store()
