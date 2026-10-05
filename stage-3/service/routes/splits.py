"""POST /splits — R-1-170..180.

A split's per-participant request can legitimately be `amount: 0`
(R-1-175), but `POST /requests` itself rejects `amount < 1` (R-1-153) —
so a split builds its request records directly rather than going
through `CreateRequestEndpoint`'s validation.
"""
from __future__ import annotations

import secrets

from ..errors import malformed_request, not_found, validation_failed
from ..json_utils import now_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..routes.requests_read import serialize_request
from ..store import STORE
from ..validation import HANDLE_RE, parse_amount, validate_note

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000
_MAX_NOTE_LEN = 200


class SplitsEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "amount" not in body or "participant_handles" not in body:
            raise validation_failed("amount and participant_handles are required")

        amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
        note = validate_note(body, max_length=_MAX_NOTE_LEN)

        # R-1-179: the array itself is a special field (422, not 400) just
        # like amount/note/visibility elsewhere; individual elements fall
        # back to the generic wrong-type rule (400) since they have no
        # special-field override of their own.
        handles = body["participant_handles"]
        if not isinstance(handles, list):
            raise validation_failed("participant_handles must be an array")
        if not handles:
            raise validation_failed("participant_handles must not be empty")

        for h in handles:
            if not isinstance(h, str):
                raise malformed_request("participant_handles entries must be strings")
        for h in handles:
            if not HANDLE_RE.match(h):
                raise validation_failed(f"invalid handle syntax: {h!r}")

        if len(set(handles)) != len(handles):
            raise validation_failed("participant_handles must not contain duplicates")

        return {"amount": amount, "note": note, "participant_handles": handles}

    def lookup(self, ctx: RequestCtx, fields: dict) -> dict:
        resolved = {}
        for handle in fields["participant_handles"]:
            user_id = STORE.users_by_handle.get(handle)
            if user_id is None:
                raise not_found(f"no such user: {handle}")
            resolved[handle] = user_id
        return resolved

    def apply(self, ctx: RequestCtx, resource: dict, fields: dict):
        caller = ctx.user
        handles = fields["participant_handles"]
        amount = fields["amount"]
        note = fields["note"]

        n = len(handles)
        base, rem = divmod(amount, n)
        share_amounts = [base + 1 if i < rem else base for i in range(n)]

        created_at = now_rfc3339()
        split_id = secrets.token_urlsafe(16)
        shares_out = []
        requests_out = []

        for handle, share_amount in zip(handles, share_amounts):
            shares_out.append({"handle": handle, "amount": share_amount})
            user_id = resource[handle]
            if user_id == caller["id"]:
                continue  # R-1-170/176: the caller gets a share, never a request
            request_id = secrets.token_urlsafe(16)
            request = {
                "id": request_id, "requester_id": caller["id"], "payer_id": user_id,
                "amount": share_amount, "note": note, "status": "pending",
                "payment_id": None, "created_at": created_at, "seq": STORE.next_seq(),
            }
            STORE.requests[request_id] = request
            requests_out.append(serialize_request(request))

        return 201, {
            "split_id": split_id, "amount": amount, "currency": STORE.currency,
            "note": note, "shares": shares_out, "requests": requests_out, "created_at": created_at,
        }


def register(router) -> None:
    router.add("POST", "/splits", SplitsEndpoint())
