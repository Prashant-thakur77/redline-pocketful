"""GET /_test/export, POST /_test/import — R-1-200..210.

The export's `state` is implementation-defined (R-1-200): this module is
the only place that knows its shape, and the only place that needs to —
R-1-202 only requires importing an *unmodified* export this same service
produced, not any particular on-the-wire format.
"""
from __future__ import annotations

from .errors import validation_failed
from .idempotency import IDEMPOTENCY

TRACK = "pocketful"
FORMAT_VERSION = 1


def export_state(store) -> dict:
    """Must be called with `store.write_lock()` held (R-1-208: an atomic,
    read-only snapshot — nothing here mutates `store`)."""
    return {
        "track": TRACK,
        "format_version": FORMAT_VERSION,
        "state": {
            "currency": store.currency,
            "minor_units": store.minor_units,
            "users": list(store.users_by_id.values()),
            "wallets": dict(store.wallets),
            "payments": list(store.payments.values()),
            "requests": list(store.requests.values()),
            "settlement_operator_ids": sorted(store.settlement_operator_ids),
            "settlements": list(store.settlements.values()),
            "tokens": dict(store.tokens),
            "next_seq": store._next_seq,
            # R-1-206: only *completed* idempotent requests are meaningful
            # to carry across — an in-flight claim has no caller waiting
            # on the other side of a process boundary.
            "idempotency": IDEMPOTENCY.export_records(),
        },
    }


def _require(obj: dict, key: str, context: str):
    if key not in obj:
        raise validation_failed(f"{context}.{key} is required")
    return obj[key]


def validate_import_document(body: dict) -> dict:
    """Builds the whole replacement state as a plain dict, same discipline
    as `fixtures.validate_fixture` — nothing here mutates the live store,
    so a rejected import changes nothing (R-1-204)."""
    track = _require(body, "track", "import")
    if track != TRACK:
        raise validation_failed(f"track must be {TRACK!r}")
    format_version = _require(body, "format_version", "import")
    if format_version != FORMAT_VERSION:
        raise validation_failed(f"format_version must be {FORMAT_VERSION}")
    state = _require(body, "state", "import")
    if not isinstance(state, dict):
        raise validation_failed("state must be an object")

    try:
        users = {u["id"]: dict(u) for u in state["users"]}
        wallets = {uid: int(balance) for uid, balance in state["wallets"].items()}
        # R-1-002: no wallet balance is ever negative, not even transiently
        # — import is unauthenticated and need not have come from this
        # service's own export, so this is a real input to validate, the
        # same way validate_fixture rejects a negative seeded balance.
        for uid, balance in wallets.items():
            if balance < 0:
                raise validation_failed(f"wallet balance for {uid} must not be negative")
        payments = {p["id"]: dict(p) for p in state["payments"]}
        requests = {r["id"]: dict(r) for r in state["requests"]}
        settlement_operator_ids = set(state["settlement_operator_ids"])
        settlements = {s["id"]: dict(s) for s in state["settlements"]}
        tokens = dict(state["tokens"])
        next_seq = int(state["next_seq"])
        idempotency_records = list(state["idempotency"])
        currency = state["currency"]
        minor_units = state["minor_units"]
        users_by_handle = {u["handle"]: u["id"] for u in users.values()}
        users_by_email = {u["email"]: u for u in users.values()}
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise validation_failed(f"state is malformed: {exc}")

    return {
        "currency": currency, "minor_units": minor_units,
        "users": users, "users_by_handle": users_by_handle, "users_by_email": users_by_email,
        "wallets": wallets, "payments": payments, "requests": requests,
        "settlement_operator_ids": settlement_operator_ids, "settlements": settlements,
        "tokens": tokens, "next_seq": next_seq, "idempotency_records": idempotency_records,
    }
