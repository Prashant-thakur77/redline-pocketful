"""GET /_test/export, POST /_test/import — R-1-200..210.

The export's `state` is implementation-defined (R-1-200): this module is
the only place that knows its shape, and the only place that needs to —
R-1-202 only requires importing an *unmodified* export this same service
produced, not any particular on-the-wire format.
"""
from __future__ import annotations

import time

from .errors import validation_failed
from .fixtures import VALID_AUTHORIZATION_STATUSES, VALID_REQUEST_STATUSES, _require_id, _require_str
from .idempotency import IDEMPOTENCY
from .invariants import check_holds_within_balance, check_nonnegative_balances
from .json_utils import parse_rfc3339
from .revisions import make_revision_1, validate_payment_history_nonnegative
from .validation import HANDLE_RE, parse_amount, validate_note, validate_visibility

TRACK = "pocketful"
FORMAT_VERSION = 1
_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000


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
            # R-3-100/102: a stage-3-origin export carries each payment's
            # full revision history verbatim -- a correction made before
            # export must still be visible after import, not collapsed
            # back to a synthesized revision 1 from the current fields.
            "payment_revisions": {pid: list(revs) for pid, revs in store.payment_revisions.items()},
        },
    }


def _require(obj: dict, key: str, context: str):
    if key not in obj:
        raise validation_failed(f"{context}.{key} is required")
    return obj[key]


def _require_int(obj: dict, key: str, context: str) -> int:
    value = _require(obj, key, context)
    if isinstance(value, bool) or not isinstance(value, int):
        raise validation_failed(f"{context}.{key} must be an integer")
    return value


def _validate_revision_record(raw, context: str) -> dict:
    if not isinstance(raw, dict):
        raise validation_failed(f"{context} must be an object")
    revision = _require_int(raw, "revision", context)
    if revision < 1:
        raise validation_failed(f"{context}.revision must be a positive integer")
    amount = parse_amount(_require(raw, "amount", context), min_value=0, max_value=_MAX_AMOUNT)
    effective_at = _require_str(raw, "effective_at", context)
    try:
        parse_rfc3339(effective_at)
    except (ValueError, TypeError):
        raise validation_failed(f"{context}.effective_at must be an RFC 3339 timestamp")
    recorded_at = _require_str(raw, "recorded_at", context)
    try:
        parse_rfc3339(recorded_at)
    except (ValueError, TypeError):
        raise validation_failed(f"{context}.recorded_at must be an RFC 3339 timestamp")
    reason = raw.get("reason", "")
    if not isinstance(reason, str):
        raise validation_failed(f"{context}.reason must be a string")
    return {"revision": revision, "amount": amount, "effective_at": effective_at,
            "recorded_at": recorded_at, "reason": reason}


def _require_optional_str(obj: dict, key: str, context: str) -> str | None:
    value = obj.get(key)
    if value is not None and not isinstance(value, str):
        raise validation_failed(f"{context}.{key} must be a string or null")
    return value


def _validate_user(raw, seen_ids: set, seen_handles: set, seen_emails: set) -> dict:
    if not isinstance(raw, dict):
        raise validation_failed("each user must be an object")
    uid = _require_id(raw, "id", "user")
    if uid in seen_ids:
        raise validation_failed("duplicate user id")
    email = _require_str(raw, "email", "user")
    if email in seen_emails:
        raise validation_failed("duplicate user email")
    # password_hash is never user-typed input (no fixture ever carries a
    # plaintext password across export/import), but it IS read again the
    # next time this user logs in — `verify_password` only swallows a
    # malformed *string* hash (ValueError from a bad "$"-split); a
    # non-string here reaches `.split` directly and raises AttributeError,
    # an uncaught 500 on a login that happens long after this import
    # returned 204.
    password_hash = _require_str(raw, "password_hash", "user")
    display_name = _require_str(raw, "display_name", "user")
    handle = _require_str(raw, "handle", "user")
    if not HANDLE_RE.match(handle):
        raise validation_failed("user handle has invalid syntax")
    if handle in seen_handles:
        raise validation_failed("duplicate user handle")
    # R-1-207: import regenerates no field it doesn't itself validate —
    # overlaying the checked fields on a copy of the raw record (rather
    # than rebuilding from scratch) preserves anything else the record
    # carried (e.g. a reset-seeded user's vestigial `balance` key) byte-
    # for-byte, so a re-export of an unmodified re-import is identical,
    # never a silently-dropped field (R-1-203's double-import stability).
    return {**raw, "id": uid, "email": email, "password_hash": password_hash,
            "display_name": display_name, "handle": handle}


def _validate_payment(raw, users: dict, seen_ids: set) -> dict:
    if not isinstance(raw, dict):
        raise validation_failed("each payment must be an object")
    pid = _require_id(raw, "id", "payment")
    if pid in seen_ids:
        raise validation_failed("duplicate payment id")
    from_user_id = _require_str(raw, "from_user_id", "payment")
    to_user_id = _require_str(raw, "to_user_id", "payment")
    if from_user_id not in users or to_user_id not in users:
        raise validation_failed("payment references an unknown user")
    amount = parse_amount(raw.get("amount"), min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
    note = validate_note(raw)
    visibility = validate_visibility(raw)
    request_id = _require_optional_str(raw, "request_id", "payment")
    settlement_id = _require_optional_str(raw, "settlement_id", "payment")
    authorization_id = _require_optional_str(raw, "authorization_id", "payment")
    created_at = _require_str(raw, "created_at", "payment")
    seq = _require_int(raw, "seq", "payment")
    return {
        **raw, "id": pid, "from_user_id": from_user_id, "to_user_id": to_user_id, "amount": amount,
        "note": note, "visibility": visibility, "request_id": request_id,
        "settlement_id": settlement_id, "authorization_id": authorization_id,
        "created_at": created_at, "seq": seq,
    }


def _validate_request_record(raw, users: dict, payments: dict, seen_ids: set) -> dict:
    """Mirrors `_validate_payment`, plus the one field that's actually
    load-bearing for a crash: `amount` feeds straight into
    `PayRequestEndpoint.apply`'s wallet arithmetic the moment someone pays
    this request post-import — a non-numeric amount reaches `-` there
    uncaught, the same shape adversary found in `remaining_amount`."""
    if not isinstance(raw, dict):
        raise validation_failed("each request must be an object")
    rid = _require_id(raw, "id", "request")
    if rid in seen_ids:
        raise validation_failed("duplicate request id")
    requester_id = _require_str(raw, "requester_id", "request")
    payer_id = _require_str(raw, "payer_id", "request")
    if requester_id not in users or payer_id not in users:
        raise validation_failed("request references an unknown user")
    amount = parse_amount(raw.get("amount"), min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
    note = validate_note(raw)
    status = raw.get("status", "pending")
    if status not in VALID_REQUEST_STATUSES:
        raise validation_failed("request status is invalid")
    payment_id = _require_optional_str(raw, "payment_id", "request")
    if payment_id is not None and payment_id not in payments:
        raise validation_failed("request.payment_id must reference a known payment")
    created_at = _require_str(raw, "created_at", "request")
    seq = _require_int(raw, "seq", "request")
    return {
        **raw, "id": rid, "requester_id": requester_id, "payer_id": payer_id, "amount": amount,
        "note": note, "status": status, "payment_id": payment_id,
        "created_at": created_at, "seq": seq,
    }


def _validate_settlement(raw, payments: dict, seen_ids: set) -> dict:
    if not isinstance(raw, dict):
        raise validation_failed("each settlement must be an object")
    sid = _require_id(raw, "id", "settlement")
    if sid in seen_ids:
        raise validation_failed("duplicate settlement id")
    committed_at = _require_str(raw, "committed_at", "settlement")
    payment_ids = raw.get("payment_ids", [])
    if not isinstance(payment_ids, list) or not all(isinstance(p, str) for p in payment_ids):
        raise validation_failed("settlement.payment_ids must be a list of strings")
    if not all(p in payments for p in payment_ids):
        raise validation_failed("settlement.payment_ids must reference known payments")
    return {**raw, "id": sid, "committed_at": committed_at, "payment_ids": list(payment_ids)}


def _validate_idempotency_record(raw) -> dict:
    """`IDEMPOTENCY.restore()` indexes these fields directly (no `.get()`)
    and runs inside `Store.apply_import`, i.e. *after* every other
    collection has already been swapped in — a crash here, uniquely among
    everything this module parses, would leave the destination
    half-replaced (exactly what R-1-204's "unchanged on any failure"
    forbids). Validating the shape here, before `apply()` ever runs,
    is what keeps that swap atomic."""
    if not isinstance(raw, dict):
        raise validation_failed("each idempotency record must be an object")
    for key in ("user_id", "method", "path", "key"):
        if not isinstance(raw.get(key), str):
            raise validation_failed(f"idempotency.{key} must be a string")
    if "request_body" not in raw:
        raise validation_failed("idempotency.request_body is required")
    response_status = raw.get("response_status")
    if isinstance(response_status, bool) or not isinstance(response_status, int):
        raise validation_failed("idempotency.response_status must be an integer")
    if "response_body" not in raw:
        raise validation_failed("idempotency.response_body is required")
    return {
        "user_id": raw["user_id"], "method": raw["method"], "path": raw["path"], "key": raw["key"],
        "request_body": raw["request_body"], "response_status": response_status,
        "response_body": raw["response_body"],
    }


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

    amount = parse_amount(raw.get("amount"), min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
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
        **raw, "id": aid, "from_user_id": from_user_id, "to_user_id": to_user_id,
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

    # Every collection below is validated field-by-field, the same
    # discipline `fixtures.validate_fixture` already applies to the reset
    # path (R-1-204a: import must not be laxer than reset) — not just
    # structurally unpacked and trusted. Order matters: later collections
    # reference earlier ones (payments reference users, requests
    # reference both users and payments, settlements reference payments),
    # so each one's referential checks can only run once its dependency
    # is already a validated dict.
    try:
        if not isinstance(state["users"], list):
            raise validation_failed("users must be a list")
        users: dict[str, dict] = {}
        users_by_handle: dict[str, str] = {}
        seen_emails: set = set()
        for raw in state["users"]:
            validated = _validate_user(raw, set(users), set(users_by_handle), seen_emails)
            users[validated["id"]] = validated
            users_by_handle[validated["handle"]] = validated["id"]
            seen_emails.add(validated["email"])
        users_by_email = {u["email"]: u for u in users.values()}

        if not isinstance(state["wallets"], dict):
            raise validation_failed("wallets must be an object")
        wallets: dict[str, int] = {}
        for uid, balance in state["wallets"].items():
            if uid not in users:
                raise validation_failed("wallets references an unknown user")
            if isinstance(balance, bool) or not isinstance(balance, int):
                raise validation_failed("wallet balance must be an integer")
            wallets[uid] = balance

        if not isinstance(state["payments"], list):
            raise validation_failed("payments must be a list")
        payments: dict[str, dict] = {}
        for raw in state["payments"]:
            validated = _validate_payment(raw, users, set(payments))
            payments[validated["id"]] = validated

        if not isinstance(state["requests"], list):
            raise validation_failed("requests must be a list")
        requests: dict[str, dict] = {}
        for raw in state["requests"]:
            validated = _validate_request_record(raw, users, payments, set(requests))
            requests[validated["id"]] = validated

        if not isinstance(state["settlement_operator_ids"], list):
            raise validation_failed("settlement_operator_ids must be a list")
        settlement_operator_ids: set = set()
        for raw in state["settlement_operator_ids"]:
            if not isinstance(raw, str) or raw not in users:
                raise validation_failed("settlement_operator_ids must reference known users")
            settlement_operator_ids.add(raw)

        if not isinstance(state["settlements"], list):
            raise validation_failed("settlements must be a list")
        settlements: dict[str, dict] = {}
        for raw in state["settlements"]:
            validated = _validate_settlement(raw, payments, set(settlements))
            settlements[validated["id"]] = validated

        if not isinstance(state["tokens"], dict):
            raise validation_failed("tokens must be an object")
        tokens: dict[str, str] = {}
        for token, uid in state["tokens"].items():
            if not isinstance(token, str) or not isinstance(uid, str) or uid not in users:
                raise validation_failed("tokens must map strings to known user ids")
            tokens[token] = uid

        next_seq = _require_int(state, "next_seq", "state")

        if not isinstance(state["idempotency"], list):
            raise validation_failed("idempotency must be a list")
        idempotency_records = [_validate_idempotency_record(raw) for raw in state["idempotency"]]

        currency = _require_str(state, "currency", "state")
        minor_units = _require(state, "minor_units", "state")
        authorization_ttl_seconds = int(state.get("authorization_ttl_seconds", 600))

        # R-2-170: a stage-1 export has no "authorizations" key at all —
        # absent means empty, the same rule R-2-021 already applies to an
        # omitted `authorizations` array on a fixture.
        authorizations: dict[str, dict] = {}
        for raw in state.get("authorizations") or []:
            validated = _validate_authorization(raw, users, set(authorizations))
            authorizations[validated["id"]] = validated

        # R-3-100/101/102: a stage-3-origin export carries each payment's
        # revision history verbatim under "payment_revisions"; a stage-1/2
        # export has no such key at all (absent means "no history exists
        # yet", the same absent-means-empty rule R-2-170 already applies
        # to "authorizations") -- every payment without an explicit entry
        # gets a synthesized revision 1 from its own created_at, never
        # from the import's own wall-clock "now" (that would make a
        # backdated correction impossible to express and would corrupt
        # every later historical read, R-3-010/011).
        payment_revisions: dict[str, list[dict]] = {}
        raw_revisions_map = state.get("payment_revisions")
        if raw_revisions_map is not None:
            if not isinstance(raw_revisions_map, dict):
                raise validation_failed("payment_revisions must be an object")
            for pid, raw_list in raw_revisions_map.items():
                if pid not in payments:
                    raise validation_failed("payment_revisions references an unknown payment")
                if not isinstance(raw_list, list) or not raw_list:
                    raise validation_failed(f"payment_revisions[{pid}] must be a non-empty list")
                payment_revisions[pid] = [
                    _validate_revision_record(raw, f"payment_revisions[{pid}][{i}]")
                    for i, raw in enumerate(raw_list)
                ]
        for pid, p in payments.items():
            if pid not in payment_revisions:
                payment_revisions[pid] = [make_revision_1(p["amount"], p["created_at"])]
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise validation_failed(f"state is malformed: {exc}")

    # R-1-204a: import enforces the same stated invariants reset does for
    # a fixture, not merely its own envelope/shape checks — the same fact
    # (a negative balance) cannot be illegal through one door and legal
    # through the other.
    check_nonnegative_balances(wallets)
    check_holds_within_balance(wallets, authorizations, time.time())
    # R-3-018/R-1-204a: the same opening-instant nonnegativity reset
    # enforces (R-3-018a/b) applies to import too — an imported state
    # implying a negative balance at any point (including the opening
    # instant, before any payment is replayed) is illegal through this
    # door exactly as it is through reset's.
    validate_payment_history_nonnegative(wallets, payments)

    return {
        "currency": currency, "minor_units": minor_units,
        "users": users, "users_by_handle": users_by_handle, "users_by_email": users_by_email,
        "wallets": wallets, "payments": payments, "requests": requests,
        "settlement_operator_ids": settlement_operator_ids, "settlements": settlements,
        "tokens": tokens, "next_seq": next_seq, "idempotency_records": idempotency_records,
        "authorizations": authorizations, "authorization_ttl_seconds": authorization_ttl_seconds,
        "payment_revisions": payment_revisions,
    }
