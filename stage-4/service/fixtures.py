"""Fixture validation for `POST /_test/reset` (R-1-030, R-1-042, R-1-047).

Builds a fully-validated replacement state as a plain dict and hands it
back untouched; nothing here mutates `STORE`. The caller swaps it in
atomically, inside the write lock, only once validation has fully
succeeded (R-1-045, R-1-047: a rejected reset changes nothing).
"""
from __future__ import annotations

import time

from .errors import validation_failed
from .invariants import check_holds_within_balance, check_nonnegative_balances
from .json_utils import now_rfc3339, parse_rfc3339
from .passwords import hash_password
from .revisions import compute_opening_balances, validate_payment_history_nonnegative
from .validation import HANDLE_RE, parse_amount, validate_note, validate_visibility

VALID_MINOR_UNITS = {0, 2, 3}
VALID_REQUEST_STATUSES = {"pending", "paid", "declined", "cancelled"}
VALID_AUTHORIZATION_STATUSES = {"open", "captured", "voided", "expired"}
MAX_ID_LEN = 64
DEFAULT_AUTHORIZATION_TTL_SECONDS = 600


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
        users[uid] = {
            "id": uid,
            "email": email,
            "password_hash": hash_password(password),
            "display_name": display_name,
            "handle": handle,
            "balance": balance,
        }
        users_by_handle[handle] = uid

    # R-3-012: a seeded payment's created_at is server time unless the
    # fixture supplies one; one shared instant for every omission, so two
    # omitted payments tie deterministically with each other too (R-3-019).
    seeded_at = now_rfc3339()
    seeded_epoch = parse_rfc3339(seeded_at)

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
        note = validate_note(raw)
        visibility = validate_visibility(raw)

        if "created_at" in raw:
            try:
                created_epoch = parse_rfc3339(raw["created_at"])
            except (ValueError, TypeError):
                raise validation_failed("payment.created_at must be an RFC 3339 timestamp")
            # R-3-013: a future seeded created_at is 422, no state change.
            if created_epoch > seeded_epoch:
                raise validation_failed("payment.created_at must not be in the future")
            created_at = raw["created_at"]
        else:
            created_at = seeded_at

        payments[pid] = {
            "id": pid, "from_user_id": from_user_id, "to_user_id": to_user_id,
            "amount": amount, "note": note, "visibility": visibility,
            "request_id": None, "settlement_id": None, "authorization_id": None,
            "created_at": created_at,
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
        note = validate_note(raw)
        status = raw.get("status", "pending")
        if status not in VALID_REQUEST_STATUSES:
            raise validation_failed("request status is invalid")

        # R-1-051: the fixture has no way to name the payment that settled a
        # seeded request, so a seeded "paid" request's payment_id stays
        # null — it is non-null only once a real POST /requests/{id}/pay
        # settles it.
        requests[rid] = {
            "id": rid, "requester_id": requester_id, "payer_id": payer_id,
            "amount": amount, "note": note, "status": status, "payment_id": None,
        }

    operator_ids: set[str] = set()
    for raw in body.get("settlement_operator_ids") or []:
        if not isinstance(raw, str):
            raise validation_failed("settlement_operator_ids must be a list of user ids")
        operator_ids.add(raw)

    # R-2-020: TTL applies to every API-created authorization, not to a
    # seeded one — a seeded authorization carries its own absolute
    # expires_at (R-2-022).
    if "authorization_ttl_seconds" not in body:
        authorization_ttl_seconds = DEFAULT_AUTHORIZATION_TTL_SECONDS
    else:
        ttl_raw = body["authorization_ttl_seconds"]
        if isinstance(ttl_raw, bool) or not isinstance(ttl_raw, int) or ttl_raw <= 0:
            raise validation_failed("authorization_ttl_seconds must be a positive integer")
        authorization_ttl_seconds = ttl_raw

    authorizations: dict[str, dict] = {}
    for raw in body.get("authorizations") or []:
        if not isinstance(raw, dict):
            raise validation_failed("each authorization must be an object")
        aid = _require_id(raw, "id", "authorization")
        if aid in authorizations:
            raise validation_failed("duplicate authorization id")
        from_user_id = _require_str(raw, "from_user_id", "authorization")
        to_user_id = _require_str(raw, "to_user_id", "authorization")
        if from_user_id not in users or to_user_id not in users:
            raise validation_failed("authorization references an unknown user")
        if from_user_id == to_user_id:
            raise validation_failed("authorization cannot reference the same user as both sides")
        amount = parse_amount(raw.get("amount"))
        note = validate_note(raw)
        visibility = validate_visibility(raw)
        status = raw.get("status", "open")
        if status not in VALID_AUTHORIZATION_STATUSES:
            raise validation_failed("authorization status is invalid")
        if "expires_at" not in raw:
            raise validation_failed("authorization.expires_at is required")
        try:
            expires_at = parse_rfc3339(raw["expires_at"])
        except (ValueError, TypeError):
            raise validation_failed("authorization.expires_at must be an RFC 3339 timestamp")

        if "captured_amount" in raw:
            captured_amount = raw["captured_amount"]
            if isinstance(captured_amount, bool) or not isinstance(captured_amount, int):
                raise validation_failed("authorization.captured_amount must be an integer")
            if captured_amount < 0 or captured_amount > amount:
                raise validation_failed("authorization.captured_amount must be between 0 and amount")
        else:
            # R-2-028: omitted defaults to 0, except the full amount when
            # the seeded status is already "captured".
            captured_amount = amount if status == "captured" else 0

        # R-3-119/120: a seeded open hold is assumed created at reset
        # unless the fixture supplies created_at; a supplied value later
        # than reset time, or later than the authorization's own
        # expires_at, is 422 -- the same shape as R-3-013's payment
        # created_at rule, so a fixture can place a hold at a chosen past
        # instant, the only way to exercise a historical hold timeline.
        if "created_at" in raw:
            try:
                auth_created_epoch = parse_rfc3339(raw["created_at"])
            except (ValueError, TypeError):
                raise validation_failed("authorization.created_at must be an RFC 3339 timestamp")
            if auth_created_epoch > seeded_epoch:
                raise validation_failed("authorization.created_at must not be in the future")
            if auth_created_epoch > expires_at:
                raise validation_failed("authorization.created_at must not be later than expires_at")
            auth_created_at = raw["created_at"]
        else:
            auth_created_at = seeded_at

        authorizations[aid] = {
            "id": aid, "from_user_id": from_user_id, "to_user_id": to_user_id,
            "amount": amount, "note": note, "visibility": visibility, "status": status,
            "expires_at": expires_at, "captured_amount": captured_amount,
            "created_at": auth_created_at,
        }

    wallets = {uid: u["balance"] for uid, u in users.items()}
    # R-1-204a: the same invariant checks reset and import both enforce,
    # not merely this endpoint's own fixture-shape rules.
    check_nonnegative_balances(wallets)
    check_holds_within_balance(wallets, authorizations, time.time())
    # R-3-018: the seeded payment history itself must never imply a
    # negative balance at any point between the opening balance and now.
    validate_payment_history_nonnegative(wallets, payments)
    opening_balances = compute_opening_balances(wallets, payments)

    return {
        "currency": currency,
        "minor_units": minor_units,
        "users": users,
        "users_by_handle": users_by_handle,
        "wallets": wallets,
        "payments": payments,
        "requests": requests,
        "settlement_operator_ids": operator_ids,
        "authorizations": authorizations,
        "authorization_ttl_seconds": authorization_ttl_seconds,
        "opening_balances": opening_balances,
    }
