"""POST /settlements — R-1-196, R-1-220..236.

R-1-227 is the whole item: affordability is decided on each wallet's
*net* delta across every transfer in the batch, never by simulating
transfers one at a time — a chain `ada->bob 100, bob->cy 100` with bob
starting at 0 must succeed (bob nets to zero), which a sequential
per-transfer check would wrongly reject.
"""
from __future__ import annotations

import secrets

from ..errors import forbidden, insufficient_funds, malformed_request, not_found, self_payment, validation_failed
from ..json_utils import now_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE
from ..validation import HANDLE_RE, parse_amount, validate_note, validate_visibility
from .payments import serialize_payment

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000
_MAX_NOTE_LEN = 200
_MAX_TRANSFERS = 32


def _validate_entry(entry) -> dict:
    if not isinstance(entry, dict):
        raise malformed_request("each transfer must be an object")
    if "from_handle" not in entry or "to_handle" not in entry or "amount" not in entry:
        raise validation_failed("from_handle, to_handle and amount are required")

    from_raw, to_raw = entry["from_handle"], entry["to_handle"]
    if not isinstance(from_raw, str) or not isinstance(to_raw, str):
        raise malformed_request("from_handle and to_handle must be strings")

    # R-1-225/R-1-223: ordinary payment amount/note/visibility rules.
    amount = parse_amount(entry["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
    note = validate_note(entry, max_length=_MAX_NOTE_LEN)
    visibility = validate_visibility(entry)

    if not HANDLE_RE.match(from_raw) or not HANDLE_RE.match(to_raw):
        raise validation_failed("handle must match ^[a-z0-9_]{1,20}$")
    # R-1-236: self_payment is only within one entry, not across the batch
    # — an operator's own handle on one side of a transfer is fine.
    if from_raw == to_raw:
        raise self_payment()

    from_user_id = STORE.users_by_handle.get(from_raw)
    to_user_id = STORE.users_by_handle.get(to_raw)
    if from_user_id is None or to_user_id is None:
        raise not_found("no such user")

    return {"from_user_id": from_user_id, "to_user_id": to_user_id, "amount": amount,
            "note": note, "visibility": visibility}


class SettlementsEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def check_permission(self, ctx: RequestCtx) -> None:
        # R-1-221/222: operator permission grants only this action, nothing
        # about visibility of other users' requests or private activity.
        if ctx.user["id"] not in STORE.settlement_operator_ids:
            raise forbidden("settlement operator required")

    def validate_fields(self, ctx: RequestCtx) -> dict:
        transfers = ctx.body.get("transfers")
        # R-1-224: the batch shape itself is a special field — 422 even for
        # the wrong JSON type, never the generic 400.
        if not isinstance(transfers, list) or not (1 <= len(transfers) <= _MAX_TRANSFERS):
            raise validation_failed("transfers must be an array of 1 to 32 entries")

        # R-1-226: entries are resolved strictly in order; the first entry
        # with any error — of whatever code — determines the response.
        resolved = [_validate_entry(entry) for entry in transfers]
        return {"transfers": resolved}

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        transfers = fields["transfers"]

        net: dict[str, int] = {}
        for t in transfers:
            net[t["from_user_id"]] = net.get(t["from_user_id"], 0) - t["amount"]
            net[t["to_user_id"]] = net.get(t["to_user_id"], 0) + t["amount"]

        # R-1-227: check every wallet's post-settlement balance before
        # touching any of them.
        for user_id, delta in net.items():
            if STORE.wallets.get(user_id, 0) + delta < 0:
                raise insufficient_funds()

        for user_id, delta in net.items():
            STORE.wallets[user_id] = STORE.wallets.get(user_id, 0) + delta

        # R-1-231: one timestamp, shared by every member and committed_at.
        committed_at = now_rfc3339()
        settlement_id = secrets.token_urlsafe(16)
        payments_out = []
        payment_ids = []
        for t in transfers:
            payment_id = secrets.token_urlsafe(16)
            payment = {
                "id": payment_id, "from_user_id": t["from_user_id"], "to_user_id": t["to_user_id"],
                "amount": t["amount"], "note": t["note"], "visibility": t["visibility"],
                "request_id": None, "settlement_id": settlement_id,
                "created_at": committed_at, "seq": STORE.next_seq(),
            }
            STORE.payments[payment_id] = payment
            payments_out.append(serialize_payment(payment))
            payment_ids.append(payment_id)

        STORE.settlements[settlement_id] = {
            "id": settlement_id, "committed_at": committed_at, "payment_ids": payment_ids,
        }
        return 201, {"settlement_id": settlement_id, "committed_at": committed_at, "payments": payments_out}


def register(router) -> None:
    router.add("POST", "/settlements", SettlementsEndpoint())
