"""POST /authorizations — R-2-016, R-2-040..046.

Capture and void are N2-3; this item only creates the hold. Field
validation and the self-payment/handle-syntax order follow R-1-076
exactly like POST /payments — authorizations are an ordinary payment
shape with a funds-check-at-the-end instead of a transfer.
"""
from __future__ import annotations

import secrets
import time

from ..errors import insufficient_funds, malformed_request, not_found, self_payment, validation_failed
from ..holds import available_for
from ..json_utils import epoch_to_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE
from ..validation import HANDLE_RE, parse_amount, validate_note, validate_visibility
from .authorizations_read import serialize_authorization

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000
_MAX_NOTE_LEN = 200


class CreateAuthorizationEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "to_handle" not in body or "amount" not in body:
            raise validation_failed("to_handle and amount are required")

        # R-1-076 order: presence -> wrong-type (non-special fields) ->
        # amount -> note -> visibility -> handle syntax -> self-reference.
        to_handle_raw = body["to_handle"]
        if not isinstance(to_handle_raw, str):
            raise malformed_request("to_handle must be a string")

        amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
        note = validate_note(body, max_length=_MAX_NOTE_LEN)
        visibility = validate_visibility(body)

        if not HANDLE_RE.match(to_handle_raw):
            raise validation_failed("to_handle must match ^[a-z0-9_]{1,20}$")
        if to_handle_raw == ctx.user["handle"]:
            raise self_payment()

        return {"to_handle": to_handle_raw, "amount": amount, "note": note, "visibility": visibility}

    def lookup(self, ctx: RequestCtx, fields: dict):
        to_user_id = STORE.users_by_handle.get(fields["to_handle"])
        if to_user_id is None:
            raise not_found("no such user")
        return STORE.users_by_id[to_user_id]

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        payer, receiver = ctx.user, resource
        amount = fields["amount"]

        # R-2-044: checked against available (total - held), not total —
        # funds are reserved, not moved, so no wallet changes either way.
        if available_for(STORE, payer["id"]) < amount:
            raise insufficient_funds()

        # One instant used for both created_at and expires_at — two separate
        # calls to "now" could straddle a second boundary and make
        # (expires_at - created_at) off by a second from the TTL (R-2-042).
        created_at_epoch = time.time()
        authorization_id = secrets.token_urlsafe(16)
        authorization = {
            "id": authorization_id,
            "from_user_id": payer["id"],
            "to_user_id": receiver["id"],
            "amount": amount,
            "note": fields["note"],
            "visibility": fields["visibility"],
            "status": "open",
            "captured_amount": 0,
            "payment_ids": [],
            "closed_at": None,
            # R-2-042: expires_at is created_at + authorization_ttl_seconds.
            "expires_at": created_at_epoch + STORE.authorization_ttl_seconds,
            "created_at": epoch_to_rfc3339(created_at_epoch),
            "seq": STORE.next_seq(),
        }
        STORE.authorizations[authorization_id] = authorization
        return 201, serialize_authorization(authorization, created_at_epoch)


def register(router) -> None:
    router.add("POST", "/authorizations", CreateAuthorizationEndpoint())
