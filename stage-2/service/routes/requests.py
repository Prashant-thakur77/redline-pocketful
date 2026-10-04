"""POST /requests, POST /requests/{id}/pay|decline|cancel — R-1-049,
R-1-051, R-1-150..162.

Permission (payer-only / requester-only) is identity-based and safe to
check before the write lock; the actual state transition — pending or
already-in-the-target-terminal-state or genuinely-not-pending — is only
ever decided inside `apply()`, under the same lock as the mutation, so a
decline racing a pay on the same request has exactly one winner (planner's
note 5): the loser re-reads `resource["status"]` live under the lock and
gets `409 request_not_pending`, never a stale "it looked pending a moment
ago" result.
"""
from __future__ import annotations

import secrets

from ..errors import (forbidden, insufficient_funds, malformed_request, not_found,
                       request_not_pending, self_request, validation_failed)
from ..json_utils import now_rfc3339
from ..pipeline import Endpoint, RequestCtx
from .payments import serialize_payment
from .requests_read import serialize_request
from ..store import STORE
from ..validation import HANDLE_RE, parse_amount, validate_note, validate_visibility

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000
_MAX_NOTE_LEN = 200


class CreateRequestEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "payer_handle" not in body or "amount" not in body:
            raise validation_failed("payer_handle and amount are required")

        payer_handle_raw = body["payer_handle"]
        if not isinstance(payer_handle_raw, str):
            raise malformed_request("payer_handle must be a string")

        amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
        note = validate_note(body, max_length=_MAX_NOTE_LEN)

        if not HANDLE_RE.match(payer_handle_raw):
            raise validation_failed("payer_handle must match ^[a-z0-9_]{1,20}$")
        if payer_handle_raw == ctx.user["handle"]:
            raise self_request()

        return {"payer_handle": payer_handle_raw, "amount": amount, "note": note}

    def lookup(self, ctx: RequestCtx, fields: dict):
        payer_id = STORE.users_by_handle.get(fields["payer_handle"])
        if payer_id is None:
            raise not_found("no such user")
        return STORE.users_by_id[payer_id]

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        # R-1-151: no affordability check here, ever — an unaffordable
        # request is legal and sits pending until money arrives.
        requester, payer = ctx.user, resource
        request_id = secrets.token_urlsafe(16)
        request = {
            "id": request_id, "requester_id": requester["id"], "payer_id": payer["id"],
            "amount": fields["amount"], "note": fields["note"], "status": "pending",
            "payment_id": None, "created_at": now_rfc3339(), "seq": STORE.next_seq(),
        }
        STORE.requests[request_id] = request
        return 201, serialize_request(request)


class PayRequestEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        return {"visibility": validate_visibility(ctx.body)}

    def lookup(self, ctx: RequestCtx, fields: dict):
        request = STORE.requests.get(ctx.path_params.get("id"))
        if request is None:
            raise not_found("no such request")
        return request

    def check_resource_permission(self, ctx: RequestCtx, resource, fields: dict) -> None:
        # R-1-158 names 403 explicitly for "a caller who is not the
        # request's payer, including a third party" — one of R-1-078's own
        # named exceptions to the general hide-as-404 rule, so a stranger
        # gets the same 403 as a wrong-role participant (e.g. the
        # requester trying to pay their own request).
        if resource["payer_id"] != ctx.user["id"]:
            raise forbidden("only the payer may pay this request")

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        request = resource
        if request["status"] != "pending":
            raise request_not_pending()

        payer = ctx.user
        requester = STORE.users_by_id.get(request["requester_id"])
        amount = request["amount"]

        payer_balance = STORE.wallets.get(payer["id"], 0)
        if payer_balance < amount:
            raise insufficient_funds()
        requester_balance = STORE.wallets.get(requester["id"], 0)

        STORE.wallets[payer["id"]] = payer_balance - amount
        STORE.wallets[requester["id"]] = requester_balance + amount

        payment_id = secrets.token_urlsafe(16)
        payment = {
            "id": payment_id, "from_user_id": payer["id"], "to_user_id": requester["id"],
            "amount": amount, "note": request["note"], "visibility": fields["visibility"],
            "request_id": request["id"], "settlement_id": None,
            "created_at": now_rfc3339(), "seq": STORE.next_seq(),
        }
        STORE.payments[payment_id] = payment
        request["status"] = "paid"
        request["payment_id"] = payment_id
        return 201, serialize_payment(payment)


class DeclineRequestEndpoint(Endpoint):
    has_body = True

    def lookup(self, ctx: RequestCtx, fields: dict):
        request = STORE.requests.get(ctx.path_params.get("id"))
        if request is None:
            raise not_found("no such request")
        return request

    def check_resource_permission(self, ctx: RequestCtx, resource, fields: dict) -> None:
        # R-1-160 names 403 for "a non-payer", the same named exception as pay.
        if resource["payer_id"] != ctx.user["id"]:
            raise forbidden("only the payer may decline this request")

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        request = resource
        if request["status"] == "declined":
            return 200, serialize_request(request)  # idempotent-by-nature repeat
        if request["status"] != "pending":
            raise request_not_pending()
        request["status"] = "declined"
        return 200, serialize_request(request)


class CancelRequestEndpoint(Endpoint):
    has_body = True

    def lookup(self, ctx: RequestCtx, fields: dict):
        request = STORE.requests.get(ctx.path_params.get("id"))
        if request is None:
            raise not_found("no such request")
        return request

    def check_resource_permission(self, ctx: RequestCtx, resource, fields: dict) -> None:
        # R-1-161 names 403 for "a non-requester", the same named exception as pay/decline.
        if resource["requester_id"] != ctx.user["id"]:
            raise forbidden("only the requester may cancel this request")

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        request = resource
        if request["status"] == "cancelled":
            return 200, serialize_request(request)  # idempotent-by-nature repeat
        if request["status"] != "pending":
            raise request_not_pending()
        request["status"] = "cancelled"
        return 200, serialize_request(request)


def register(router) -> None:
    router.add("POST", "/requests", CreateRequestEndpoint())
    router.add("POST", "/requests/{id}/pay", PayRequestEndpoint())
    router.add("POST", "/requests/{id}/decline", DeclineRequestEndpoint())
    router.add("POST", "/requests/{id}/cancel", CancelRequestEndpoint())
