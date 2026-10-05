"""POST /authorizations/{id}/capture, POST /authorizations/{id}/void —
R-2-050..075.

Permission is identity-based and safe to check before the write lock
(R-2-074: any non-permitted caller, including a total stranger, is a
flat 403 — no two-tier visibility split here, unlike stage 1's original
requests.py mistake). The actual state transition and the funds movement
are decided together inside `apply()`, under the lock, re-reading the
authorization's *current* status live — the same race-safety shape as
stage 1's request pay/decline/cancel, and for the same reason: a capture
racing a void must have exactly one winner (R-2-181/182).
"""
from __future__ import annotations

import secrets
import time

from ..errors import (authorization_expired, authorization_not_open, capture_exceeds_authorization,
                       forbidden, not_found, validation_failed)
from ..holds import effective_status, remaining_amount
from ..json_utils import now_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import make_revision_1
from ..store import STORE
from ..validation import parse_amount
from .authorizations_read import serialize_authorization
from .payments import serialize_payment

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000


class CaptureEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        # R-2-051: both optional. R-2-064: wrong type/range on either is
        # 422 validation_failed; capture_exceeds_authorization needs the
        # authorization's remainder, so it waits for lookup/state (below).
        amount = None
        if "amount" in body:
            amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
        final = True
        if "final" in body:
            final_raw = body["final"]
            if not isinstance(final_raw, bool):
                raise validation_failed("final must be a boolean")
            final = final_raw
        return {"amount": amount, "final": final}

    def lookup(self, ctx: RequestCtx, fields: dict):
        authorization = STORE.authorizations.get(ctx.path_params.get("id"))
        if authorization is None:
            raise not_found("no such authorization")
        return authorization

    def check_resource_permission(self, ctx: RequestCtx, resource, fields: dict) -> None:
        # R-2-074: only the receiver may capture; any other caller,
        # including one who is neither party, is 403 — not hidden as 404.
        if resource["to_user_id"] != ctx.user["id"]:
            raise forbidden("only the receiver may capture this authorization")

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        authorization = resource
        now = time.time()

        # R-2-065: expired-by-clock (still stored "open") beats
        # not-open; already-closed (captured/voided) is not-open.
        status = effective_status(authorization, now)
        if status == "expired":
            raise authorization_expired()
        if status != "open":
            raise authorization_not_open()

        remaining = remaining_amount(authorization)
        amount = fields["amount"] if fields["amount"] is not None else remaining
        # R-2-060: compared against the remainder, not the original amount.
        if amount > remaining:
            raise capture_exceeds_authorization()

        payer_id, receiver_id = authorization["from_user_id"], authorization["to_user_id"]

        # R-2-066: this money is already reserved by the hold — spend it
        # directly, never through an available_for() funds check.
        STORE.wallets[payer_id] = STORE.wallets.get(payer_id, 0) - amount
        STORE.wallets[receiver_id] = STORE.wallets.get(receiver_id, 0) + amount

        capture_at = now_rfc3339()
        authorization["captured_amount"] = authorization.get("captured_amount", 0) + amount
        new_remaining = authorization["amount"] - authorization["captured_amount"]
        # R-3-111: a nonfinal capture reduces the hold AT CAPTURE TIME, not
        # retroactively -- each capture needs its own recorded instant so a
        # historical `held` view can reconstruct what was captured by a
        # given as_of, not just the current running total.
        authorization.setdefault("capture_events", []).append({"amount": amount, "at": capture_at})

        payment_id = secrets.token_urlsafe(16)
        payment = {
            "id": payment_id, "from_user_id": payer_id, "to_user_id": receiver_id,
            "amount": amount, "note": authorization["note"], "visibility": authorization["visibility"],
            "request_id": None, "settlement_id": None, "authorization_id": authorization["id"],
            "created_at": now_rfc3339(), "seq": STORE.next_seq(),
        }
        STORE.payments[payment_id] = payment
        # R-3-003/R-3-103: a capture-produced payment carries a revision 1
        # like any other payment.
        STORE.payment_revisions[payment_id] = [make_revision_1(amount, payment["created_at"])]
        authorization.setdefault("payment_ids", []).append(payment_id)

        # R-2-056/058/059: final, or the remainder fully captured, closes
        # the hold and releases whatever is left in the same step — the
        # release itself needs no extra code, since a closed authorization
        # is excluded from held_for() from this point on.
        if fields["final"] or new_remaining == 0:
            authorization["status"] = "captured"
            authorization["closed_at"] = capture_at

        return 201, serialize_payment(payment)


class VoidEndpoint(Endpoint):
    has_body = True

    def lookup(self, ctx: RequestCtx, fields: dict):
        authorization = STORE.authorizations.get(ctx.path_params.get("id"))
        if authorization is None:
            raise not_found("no such authorization")
        return authorization

    def check_resource_permission(self, ctx: RequestCtx, resource, fields: dict) -> None:
        # R-2-070/074: only the payer may void; any other caller is 403.
        if resource["from_user_id"] != ctx.user["id"]:
            raise forbidden("only the payer may void this authorization")

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        authorization = resource
        now = time.time()
        status = effective_status(authorization, now)

        if status == "voided":
            return 200, serialize_authorization(authorization, now)  # R-2-072: idempotent-by-nature repeat

        # R-2-073: void never distinguishes expired from captured — both
        # are simply "not open" for this endpoint (unlike capture's
        # R-2-065 split).
        if status != "open":
            raise authorization_not_open()

        authorization["status"] = "voided"
        authorization["closed_at"] = now_rfc3339()
        return 200, serialize_authorization(authorization, now)


def register(router) -> None:
    router.add("POST", "/authorizations/{id}/capture", CaptureEndpoint())
    router.add("POST", "/authorizations/{id}/void", VoidEndpoint())
