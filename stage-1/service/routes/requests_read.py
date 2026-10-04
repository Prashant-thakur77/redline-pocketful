"""GET /requests — R-1-163..167, read-only (create/pay/decline/cancel are
N1-6's scope; this wired early because the storm invariant, gate 4, reads
it for every user after every operation).
"""
from __future__ import annotations

from ..errors import validation_failed
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE
from ..validation import parse_limit, parse_offset

_VALID_DIRECTIONS = {"incoming", "outgoing"}
_VALID_STATUSES = {"pending", "paid", "declined", "cancelled"}


class RequestsListEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        direction = ctx.query.get("direction")
        if direction is not None and direction not in _VALID_DIRECTIONS:
            raise validation_failed('direction must be "incoming" or "outgoing"')
        status = ctx.query.get("status")
        if status is not None and status not in _VALID_STATUSES:
            raise validation_failed("status must be one of pending/paid/declined/cancelled")
        return {
            "limit": parse_limit(ctx.query.get("limit")),
            "offset": parse_offset(ctx.query.get("offset")),
            "direction": direction,
            "status": status,
        }

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user_id = ctx.user["id"]
        direction, status = fields["direction"], fields["status"]

        visible = []
        for r in STORE.requests.values():
            is_requester = r["requester_id"] == user_id
            is_payer = r["payer_id"] == user_id
            if not (is_requester or is_payer):
                continue
            if direction == "outgoing" and not is_requester:
                continue
            if direction == "incoming" and not is_payer:
                continue
            if status is not None and r["status"] != status:
                continue
            visible.append(r)
        visible.sort(key=lambda r: r["seq"], reverse=True)

        limit, offset = fields["limit"], fields["offset"]
        page = visible[offset:offset + limit]
        has_more = offset + limit < len(visible)

        out = []
        for r in page:
            requester = STORE.users_by_id.get(r["requester_id"])
            payer = STORE.users_by_id.get(r["payer_id"])
            out.append({
                "request_id": r["id"],
                "requester_id": r["requester_id"],
                "requester_handle": requester["handle"] if requester else None,
                "payer_id": r["payer_id"],
                "payer_handle": payer["handle"] if payer else None,
                "amount": r["amount"],
                "currency": STORE.currency,
                "note": r["note"],
                "status": r["status"],
                "payment_id": r["payment_id"],
                "created_at": r["created_at"],
            })
        return 200, {"requests": out, "has_more": has_more}


def register(router) -> None:
    router.add("GET", "/requests", RequestsListEndpoint())
