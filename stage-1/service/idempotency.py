"""The shared idempotency layer every write path uses (R-1-100..112).

Three states per (user, method, path, key): *unclaimed* (no entry),
*in flight* (claimed, operation running), *complete* (status+body stored
verbatim). `resolve_or_claim` is the only way in: it either hands the
caller the stored response (a true replay, or a conflict), or marks the
caller as the one request that must actually run the operation.

"Same body" (R-1-106) is decided by comparing the **parsed** JSON value
with `==`, not the raw bytes: Python already treats `1000 == 1000.0 ==
1e3` and ignores dict key order, which is exactly R-1-106's rule, while
list equality stays order-sensitive, also exactly as required. Unknown
fields are never stripped before this comparison, so they are part of
the body like any other field.

The claim and the eventual commit/release are deliberately NOT the same
lock as the store's funds lock (`Store.write_lock()`) — claiming must be
fast and non-blocking for the winner so field validation and lookups
(which take no shared-state lock) don't serialize behind it, while losers
with the SAME body block on an `Event` until the winner finishes, so
"exactly one 201, the rest 200" (R-1-108) holds even under 50-way
concurrency without ever observing a gap. A loser with a DIFFERENT body
also waits — only once the winner's outcome is known can "same key,
different body" (409) be told apart from "the winner's claim was
released, so this call becomes the new first use" (R-1-107).
"""
from __future__ import annotations

import threading

from .errors import idempotency_key_reuse

_WAIT_TIMEOUT = 15.0  # generous relative to R-1-015's 5s/10s request budgets


class _Entry:
    __slots__ = ("request_body", "state", "response_status", "response_body", "event")

    def __init__(self, request_body):
        self.request_body = request_body
        self.state = "in_flight"  # or "complete"
        self.response_status: int | None = None
        self.response_body = None
        self.event = threading.Event()


class IdempotencyStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[tuple, _Entry] = {}

    def resolve_or_claim(self, user_id: str, method: str, path: str, key: str, body):
        """Returns `("claimed", composite_key)` — the caller must run the
        operation and call `commit`/`release` on that composite key — or
        `("replay", (200, body))` — the caller must return that response
        as-is. Raises `idempotency_key_reuse` for a same-key, different-
        body conflict once the conflicting record is known to be complete."""
        composite = (user_id, method, path, key)
        while True:
            with self._lock:
                entry = self._entries.get(composite)
                if entry is None:
                    self._entries[composite] = _Entry(body)
                    return "claimed", composite
                if entry.state == "complete":
                    if entry.request_body != body:
                        raise idempotency_key_reuse()
                    return "replay", (200, entry.response_body)
                event = entry.event
            # in flight (by this body or a different one): wait for the
            # winner to commit or release, then re-check from scratch —
            # a release means this call becomes the new first use.
            event.wait(_WAIT_TIMEOUT)

    def commit(self, composite: tuple, status: int, body) -> None:
        """R-1-111/R-1-112: store the response verbatim — never a reference
        to a resource that could be re-rendered differently later."""
        with self._lock:
            entry = self._entries.get(composite)
            if entry is None:
                return
            entry.state = "complete"
            entry.response_status = status
            entry.response_body = body
            entry.event.set()

    def release(self, composite: tuple) -> None:
        """R-1-107: a key whose claimed operation failed (any 4xx, or an
        unexpected error) is never left claimed — the next use, same body
        or not, is a genuine first use."""
        with self._lock:
            entry = self._entries.pop(composite, None)
            if entry is not None:
                entry.event.set()

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


IDEMPOTENCY = IdempotencyStore()
