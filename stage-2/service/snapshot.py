"""GET /_test/export, POST /_test/import — R-1-200..210.

The export's `state` is implementation-defined (R-1-200): this module is
the only place that knows its shape, and the only place that needs to —
R-1-202 only requires importing an *unmodified* export this same service
produced, not any particular on-the-wire format.
"""
from __future__ import annotations

import time

from .errors import validation_failed
from .fixtures import VALID_AUTHORIZATION_STATUSES
from .idempotency import IDEMPOTENCY
from .invariants import check_holds_within_balance, check_nonnegative_balances
from .validation import parse_amount, validate_note, validate_visibility

TRACK = "pocketful"
FORMAT_VERSION = 1
_MIN_AUTHORIZATION_AMOUNT = 1
_MAX_AUTHORIZATION_AMOUNT = 1_000_000_000


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
            # R-2-175: authorizations round-trip verbatim, including their
            # raw expires_at epoch — status/held are derived from it at
            # read time (R-2-030), never recomputed or frozen here.
            "authorizations": list(store.authorizations.values()),
            "authorization_ttl_seconds": store.authorization_ttl_seconds,
        },
    }


def _require(obj: dict, key: str, context: str):
    if key not in obj:
        raise validation_failed(f"{context}.{key} is required")
    return obj[key]


def _validate_authorization(raw, users: dict, seen_ids: set) -> dict:
    """Per-field validation for one imported authorization — the same
    discipline `fixtures.validate_fixture` already applies to a seeded
    one (R-1-204a), so a crafted import can't reach `check_holds_within_
    balance` with a field it can't tolerate (R-1-005/R-1-204: malformed
    input is 422, never a crash, and never silently accepted)."""
    if not isinstance(raw, dict):
        raise validation_failed("each authorization must be an object")
    aid = _require(raw, "id", "authorization")
    if not isinstance(aid, str) or not aid:
        raise validation_failed("authorization.id must be a non-empty string")
    if aid in seen_ids:
        raise validation_failed("duplicate authorization id")
    from_user_id = _require(raw, "from_user_id", "authorization")
    to_user_id = _require(raw, "to_user_id", "authorization")
    if not isinstance(from_user_id, str) or not isinstance(to_user_id, str):
        raise validation_failed("authorization.from_user_id/to_user_id must be strings")
    if from_user_id not in users or to_user_id not in users:
        raise validation_failed("authorization references an unknown user")
    if from_user_id == to_user_id:
        raise validation_failed("authorization cannot reference the same user as both sides")

    amount = parse_amount(raw.get("amount"), min_value=_MIN_AUTHORIZATION_AMOUNT,
                           max_value=_MAX_AUTHORIZATION_AMOUNT)
    note = validate_note(raw)
    visibility = validate_visibility(raw)
    status = raw.get("status", "open")
    if status not in VALID_AUTHORIZATION_STATUSES:
        raise validation_failed("authorization status is invalid")

    expires_at_raw = _require(raw, "expires_at", "authorization")
    if isinstance(expires_at_raw, bool) or not isinstance(expires_at_raw, (int, float)):
        # An export's expires_at is the raw internal epoch number, never a
        # string (that's the fixture/wire format, not this one — R-1-200).
        raise validation_failed("authorization.expires_at must be a number")
    expires_at = float(expires_at_raw)

    captured_amount = raw.get("captured_amount", 0)
    if isinstance(captured_amount, bool) or not isinstance(captured_amount, int):
        raise validation_failed("authorization.captured_amount must be an integer")
    if captured_amount < 0 or captured_amount > amount:
        raise validation_failed("authorization.captured_amount must be between 0 and amount")

    payment_ids = raw.get("payment_ids", [])
    if not isinstance(payment_ids, list) or not all(isinstance(p, str) for p in payment_ids):
        raise validation_failed("authorization.payment_ids must be a list of strings")

    closed_at = raw.get("closed_at")
    if closed_at is not None and not isinstance(closed_at, str):
        raise validation_failed("authorization.closed_at must be a string or null")

    created_at = _require(raw, "created_at", "authorization")
    if not isinstance(created_at, str) or not created_at:
        raise validation_failed("authorization.created_at must be a non-empty string")

    seq = raw.get("seq", 0)
    if isinstance(seq, bool) or not isinstance(seq, int):
        raise validation_failed("authorization.seq must be an integer")

    return {
        "id": aid, "from_user_id": from_user_id, "to_user_id": to_user_id,
        "amount": amount, "note": note, "visibility": visibility, "status": status,
        "captured_amount": captured_amount, "payment_ids": list(payment_ids),
        "closed_at": closed_at, "expires_at": expires_at, "created_at": created_at, "seq": seq,
    }


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
        authorization_ttl_seconds = int(state.get("authorization_ttl_seconds", 600))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise validation_failed(f"state is malformed: {exc}")

    # R-2-170: a stage-1 export has no "authorizations" key at all — absent
    # means empty, the same rule R-2-021 already applies to an omitted
    # `authorizations` array on a fixture. Each present one is validated
    # field-by-field below (never copied verbatim) before anything —
    # including `check_holds_within_balance` below — reads it.
    authorizations: dict[str, dict] = {}
    for raw in state.get("authorizations") or []:
        validated = _validate_authorization(raw, users, set(authorizations))
        authorizations[validated["id"]] = validated

    # R-1-204a: import enforces the same stated invariants reset does for
    # a fixture, not merely its own envelope/shape checks — the same fact
    # (a negative balance) cannot be illegal through one door and legal
    # through the other.
    check_nonnegative_balances(wallets)
    check_holds_within_balance(wallets, authorizations, time.time())

    return {
        "currency": currency, "minor_units": minor_units,
        "users": users, "users_by_handle": users_by_handle, "users_by_email": users_by_email,
        "wallets": wallets, "payments": payments, "requests": requests,
        "settlement_operator_ids": settlement_operator_ids, "settlements": settlements,
        "tokens": tokens, "next_seq": next_seq, "idempotency_records": idempotency_records,
        "authorizations": authorizations, "authorization_ttl_seconds": authorization_ttl_seconds,
    }
