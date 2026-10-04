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


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self.reset_generation = 0
        self.currency = "EUR"
        self.minor_units = 2
        self.users_by_id: dict[str, dict] = {}
        self.users_by_handle: dict[str, dict] = {}
        self.users_by_email: dict[str, dict] = {}
        self.wallets: dict[str, int] = {}
        self.payments: dict[str, dict] = {}
        self.requests: dict[str, dict] = {}
        self.settlements: dict[str, dict] = {}
        self.settlement_operator_ids: set[str] = set()
        self.tokens: dict[str, str] = {}  # token -> user_id

    def write_lock(self):
        """Context manager: hold this for the whole check-and-apply of a
        money-moving write, never just for the funds check alone."""
        return self._lock

    def reset(self):
        with self._lock:
            self.reset_generation += 1
            self.currency = "EUR"
            self.minor_units = 2
            self.users_by_id.clear()
            self.users_by_handle.clear()
            self.users_by_email.clear()
            self.wallets.clear()
            self.payments.clear()
            self.requests.clear()
            self.settlements.clear()
            self.settlement_operator_ids.clear()
            self.tokens.clear()


STORE = Store()
