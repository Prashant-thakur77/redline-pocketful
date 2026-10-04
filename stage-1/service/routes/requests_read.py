"""GET /requests — read-only minimal slice, wired in N1-2 only because the
storm invariant (gate 4) reads it for every user after every operation.

Full request lifecycle — create, pay, decline, cancel, direction/status
filters (R-1-150..167) — is N1-6's scope. This endpoint only guarantees
R-1-163 (visible to participants only, newest first) and basic
limit/offset pagination so the invariant can run; N1-6 extends it rather
than replacing it.
"""
from __future__ import annotations

from ..pipeline import Endpoint, RequestCtx
from ..store import STORE
from ..validation import parse_limit, parse_offset


class RequestsListEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        return {
            "limit": parse_limit(ctx.query.get("limit")),
            "offset": parse_offset(ctx.query.get("offset")),
        }

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user_id = ctx.user["id"]
        visible = [r for r in STORE.requests.values()
                   if r["requester_id"] == user_id or r["payer_id"] == user_id]
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
