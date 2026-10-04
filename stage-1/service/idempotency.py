"""The shared idempotency layer every write path uses (R-1-100..112).

Three states per (user, method, path, key): *unclaimed* (no entry),
*in flight* (claimed, operation running), *complete* (status+body stored
verbatim). `resolve_or_claim` is the only way in: it either hands the
caller the stored response (a true replay, or a conflict), or marks the
caller as the one request that must actually run the operation.

"Same body" (R-1-106) is decided by comparing the **parsed** JSON value
with `json_equal` below, not the raw bytes and not bare `==`: Python's
`==` already gets numbers right (`1000 == 1000.0 == 1e3`) and ignores
dict key order while keeping list order significant, which is exactly
R-1-106's rule — but it also makes `True == 1`, which would silently
treat a boolean and a number as the same JSON value. `json_equal` keeps
the former and rejects the latter. Unknown fields are never stripped
before this comparison, so they are part of the body like any other
field.

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


def json_equal(a, b) -> bool:
    """R-1-106: the same JSON value after parsing. Numbers compare by
    exact numeric value across int/float (`1000 == 1000.0 == 1e3`); a
    bool is only equal to a bool of the same value, never to a number
    even though Python's bare `==` would say `True == 1`; dict key order
    is irrelevant; list order is significant."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(json_equal(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(json_equal(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


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
                    if not json_equal(entry.request_body, body):
                        raise idempotency_key_reuse()
                    return "replay", (200, entry.response_body)
                event = entry.event
            # In flight (by this body or a different one): wait with no
            # timeout. R-1-080b: a slow winner, a starved thread or an
            # entry removed under us are all *anticipated* conditions, not
            # bugs, so this may never answer them with a 500 — the only
            # way out that is licensed is a correct response. R-1-112a
            # makes that safe: every path that can remove this entry
            # before it completes (`release`, `clear`, `restore`) signals
            # this exact event first, so the wait is bounded by the real
            # winner's own R-1-015 compliance, not by a wall clock here.
            # No lost wakeup: `event` was read under the lock above, and
            # `Event.set()` latches — a `set()` landing between releasing
            # that lock and this `wait()` call still makes `wait()` return
            # immediately, it does not need to already be blocked.
            event.wait()

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
        """R-1-040/R-1-112a: wake every waiter parked on an incomplete
        entry before dropping it — otherwise a reset concurrent with
        in-flight traffic leaves those callers blocked forever, since
        nothing else will ever set their event. A woken waiter re-checks
        from scratch, finds no entry, and becomes a genuine first use."""
        with self._lock:
            for entry in self._entries.values():
                if entry.state != "complete":
                    entry.event.set()
            self._entries.clear()

    def export_records(self) -> list[dict]:
        """R-1-206/111: only *completed* records are meaningful to carry
        across export/import — an in-flight claim has no caller waiting
        on the other side of a process boundary."""
        with self._lock:
            return [
                {"user_id": uid, "method": method, "path": path, "key": key,
                 "request_body": entry.request_body,
                 "response_status": entry.response_status,
                 "response_body": entry.response_body}
                for (uid, method, path, key), entry in self._entries.items()
                if entry.state == "complete"
            ]

    def restore(self, records: list[dict]) -> None:
        """R-1-201/203/206: import *replaces* the whole table with these
        completed records — the mirror of `clear()`, which reset uses
        instead (R-1-209: reset clears even imported state). Same
        R-1-112a obligation as `clear()`: wake incomplete entries' waiters
        *before* dropping them, so none hangs on an event an import can
        never set otherwise."""
        with self._lock:
            for entry in self._entries.values():
                if entry.state != "complete":
                    entry.event.set()
            self._entries.clear()
            for rec in records:
                composite = (rec["user_id"], rec["method"], rec["path"], rec["key"])
                entry = _Entry(rec["request_body"])
                entry.state = "complete"
                entry.response_status = rec["response_status"]
                entry.response_body = rec["response_body"]
                self._entries[composite] = entry


IDEMPOTENCY = IdempotencyStore()
