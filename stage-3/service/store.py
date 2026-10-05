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
from .revisions import compute_opening_balances, ordered_by_time_then_id, seed_revisions


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
        self.authorizations: dict[str, dict] = {}
        self.authorization_ttl_seconds: int = 600
        self.payment_revisions: dict[str, list[dict]] = {}
        self.opening_balances: dict[str, int] = {}
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
        # R-3-019: seq (the "newest first" tie-break elsewhere) follows the
        # same chronological-then-id order as every other ordering
        # requirement, not raw fixture-list order — created_at is now
        # per-payment (R-3-012), not forced to one shared instant.
        for payment in ordered_by_time_then_id(fields["payments"]):
            payment["seq"] = self.next_seq()
        for request in fields["requests"].values():
            request["created_at"] = seeded_at
            request["seq"] = self.next_seq()
        for authorization in fields["authorizations"].values():
            authorization["created_at"] = seeded_at
            authorization["seq"] = self.next_seq()

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
        self.authorizations = fields["authorizations"]
        self.authorization_ttl_seconds = fields["authorization_ttl_seconds"]
        # R-3-003: revision 1 for every seeded payment, from the instant it
        # exists — never deferred to its first correction. R-3-016: the
        # opening balance fixtures.py already derived from the same
        # payments, carried through unchanged.
        self.payment_revisions = seed_revisions(fields["payments"])
        self.opening_balances = fields["opening_balances"]
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
        # R-2-170/175: an export from this service carries authorizations
        # verbatim; a stage-1 export has no such key, and `validate_import_
        # document` already defaults that case to empty (absent means
        # empty, same as R-2-021 for a fixture) — nothing special to do
        # here beyond assigning what was parsed.
        self.authorizations = fields["authorizations"]
        self.authorization_ttl_seconds = fields["authorization_ttl_seconds"]
        # R-3-003: a stage-1/stage-2 export carries no revision history at
        # all, so every imported payment gets a synthesized revision 1 from
        # its own created_at — the same "every payment that EXISTS gets a
        # revision 1" rule seeded payments get, applied to the import path
        # named explicitly as a trap. (No payment can yet have more than one
        # revision — corrections don't exist until N3-2 — so this can't
        # yet collapse a real correction history; once corrections exist,
        # a stage-3-origin export must carry revisions verbatim instead of
        # resynthesizing them here.)
        self.payment_revisions = seed_revisions(fields["payments"])
        self.opening_balances = compute_opening_balances(fields["wallets"], fields["payments"])
        IDEMPOTENCY.restore(fields["idempotency_records"])


STORE = Store()
