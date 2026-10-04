"""Fixture validation for `POST /_test/reset` (R-1-030, R-1-042, R-1-047).

Builds a fully-validated replacement state as a plain dict and hands it
back untouched; nothing here mutates `STORE`. The caller swaps it in
atomically, inside the write lock, only once validation has fully
succeeded (R-1-045, R-1-047: a rejected reset changes nothing).
"""
from __future__ import annotations

from .errors import validation_failed
from .passwords import hash_password
from .validation import HANDLE_RE, parse_amount, validate_note, validate_visibility

VALID_MINOR_UNITS = {0, 2, 3}
VALID_REQUEST_STATUSES = {"pending", "paid", "declined", "cancelled"}
MAX_ID_LEN = 64


def _require_str(obj: dict, key: str, context: str) -> str:
    if key not in obj:
        raise validation_failed(f"{context}.{key} is required")
    value = obj[key]
    if not isinstance(value, str) or not value:
        raise validation_failed(f"{context}.{key} must be a non-empty string")
    return value


def _require_id(obj: dict, key: str, context: str) -> str:
    value = _require_str(obj, key, context)
    if len(value) > MAX_ID_LEN:
        raise validation_failed(f"{context}.{key} must be at most {MAX_ID_LEN} characters")
    return value


def validate_fixture(body: dict) -> dict:
    if "currency" not in body:
        raise validation_failed("currency is required")
    currency = body["currency"]
    if not isinstance(currency, str) or not currency:
        raise validation_failed("currency must be a non-empty string")

    if "minor_units" not in body:
        raise validation_failed("minor_units is required")
    minor_units = body["minor_units"]
    if isinstance(minor_units, bool) or not isinstance(minor_units, int) or minor_units not in VALID_MINOR_UNITS:
        raise validation_failed("minor_units must be 0, 2 or 3")

    if "users" not in body or not isinstance(body["users"], list):
        raise validation_failed("users must be a list")

    users: dict[str, dict] = {}
    users_by_handle: dict[str, str] = {}
    for raw in body["users"]:
        if not isinstance(raw, dict):
            raise validation_failed("each user must be an object")
        uid = _require_id(raw, "id", "user")
        if uid in users:
            raise validation_failed("duplicate user id")
        email = _require_str(raw, "email", "user")
        password = _require_str(raw, "password", "user")
        display_name = _require_str(raw, "display_name", "user")
        handle = _require_str(raw, "handle", "user")
        if not HANDLE_RE.match(handle):
            raise validation_failed("user handle has invalid syntax")
        if handle in users_by_handle:
            raise validation_failed("duplicate user handle")
        if "balance" not in raw:
            raise validation_failed("user.balance is required")
        balance = parse_amount(raw["balance"])
        if balance < 0:
            raise validation_failed("user balance must not be negative")
        users[uid] = {
            "id": uid,
            "email": email,
            "password_hash": hash_password(password),
            "display_name": display_name,
            "handle": handle,
            "balance": balance,
        }
        users_by_handle[handle] = uid

    payments: dict[str, dict] = {}
    for raw in body.get("payments") or []:
        if not isinstance(raw, dict):
            raise validation_failed("each payment must be an object")
        pid = _require_id(raw, "id", "payment")
        if pid in payments:
            raise validation_failed("duplicate payment id")
        from_user_id = _require_str(raw, "from_user_id", "payment")
        to_user_id = _require_str(raw, "to_user_id", "payment")
        if from_user_id not in users or to_user_id not in users:
            raise validation_failed("payment references an unknown user")
        amount = parse_amount(raw.get("amount"))
        note = validate_note(raw.get("note"))
        visibility = validate_visibility(raw.get("visibility"))
        payments[pid] = {
            "id": pid, "from_user_id": from_user_id, "to_user_id": to_user_id,
            "amount": amount, "note": note, "visibility": visibility, "settlement_id": None,
        }

    requests: dict[str, dict] = {}
    for raw in body.get("requests") or []:
        if not isinstance(raw, dict):
            raise validation_failed("each request must be an object")
        rid = _require_id(raw, "id", "request")
        if rid in requests:
            raise validation_failed("duplicate request id")
        requester_id = _require_str(raw, "requester_id", "request")
        payer_id = _require_str(raw, "payer_id", "request")
        if requester_id not in users or payer_id not in users:
            raise validation_failed("request references an unknown user")
        amount = parse_amount(raw.get("amount"))
        note = validate_note(raw.get("note"))
        status = raw.get("status", "pending")
        if status not in VALID_REQUEST_STATUSES:
            raise validation_failed("request status is invalid")

        payment_id = None
        if status == "paid":
            # R-1-042's request fields have no way to name the payment that
            # settled a seeded request, so a seeded "paid" request implies
            # one: synthesize it the same way an API-driven pay would have
            # produced it (payer -> requester, same amount/note).
            payment_id = f"seed-settle-{rid}"
            if payment_id in payments or len(payment_id) > MAX_ID_LEN:
                raise validation_failed("could not derive a settlement payment id for a seeded paid request")
            payments[payment_id] = {
                "id": payment_id, "from_user_id": payer_id, "to_user_id": requester_id,
                "amount": amount, "note": note, "visibility": "private", "settlement_id": None,
            }
        requests[rid] = {
            "id": rid, "requester_id": requester_id, "payer_id": payer_id,
            "amount": amount, "note": note, "status": status, "payment_id": payment_id,
        }

    operator_ids: set[str] = set()
    for raw in body.get("settlement_operator_ids") or []:
        if not isinstance(raw, str):
            raise validation_failed("settlement_operator_ids must be a list of user ids")
        operator_ids.add(raw)

    return {
        "currency": currency,
        "minor_units": minor_units,
        "users": users,
        "users_by_handle": users_by_handle,
        "wallets": {uid: u["balance"] for uid, u in users.items()},
        "payments": payments,
        "requests": requests,
        "settlement_operator_ids": operator_ids,
    }
