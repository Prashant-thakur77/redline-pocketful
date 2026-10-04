"""Generic idempotency-key bookkeeping (precedence step 6, R-1-066).

The full replay/caching semantics (R-1-100..111) are N1-4's scope. This item
provides the shared lookup/record primitives — keyed by caller, method,
path and key — so every write endpoint resolves idempotency the same way
and N1-4 only has to fill in what gets cached.
"""
from __future__ import annotations

import hashlib
import threading

from .errors import idempotency_key_reuse


class IdempotencyStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str, str, str], tuple[str, int, dict]] = {}

    @staticmethod
    def _body_hash(raw_body: bytes) -> str:
        return hashlib.sha256(raw_body or b"").hexdigest()

    def resolve(self, user_id: str, method: str, path: str, key: str, raw_body: bytes):
        """Return the cached (status, body) for a replay, or None if this is
        a new key. Raises idempotency_key_reuse if the key was used before
        by this caller on this method+path with a different body."""
        body_hash = self._body_hash(raw_body)
        with self._lock:
            entry = self._entries.get((user_id, method, path, key))
            if entry is None:
                return None
            stored_hash, status, body = entry
            if stored_hash != body_hash:
                raise idempotency_key_reuse()
            return status, body

    def record(self, user_id: str, method: str, path: str, key: str, raw_body: bytes,
               status: int, body: dict) -> None:
        body_hash = self._body_hash(raw_body)
        with self._lock:
            self._entries[(user_id, method, path, key)] = (body_hash, status, body)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


IDEMPOTENCY = IdempotencyStore()
