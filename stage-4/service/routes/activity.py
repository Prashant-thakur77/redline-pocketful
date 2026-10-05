"""GET /activity — the feed contract, R-1-190..196."""
from __future__ import annotations

from ..pipeline import Endpoint, RequestCtx
from ..store import STORE
from ..validation import parse_limit, parse_offset
from .payments import serialize_payment


class ActivityEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        return {
            "limit": parse_limit(ctx.query.get("limit")),
            "offset": parse_offset(ctx.query.get("offset")),
        }

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user_id = ctx.user["id"]
        # R-1-191: public, or the caller is sender, or the caller is receiver
        # — no other rule.
        visible = [p for p in STORE.payments.values()
                   if p["visibility"] == "public" or p["from_user_id"] == user_id
                   or p["to_user_id"] == user_id]
        visible.sort(key=lambda p: p["seq"], reverse=True)

        limit, offset = fields["limit"], fields["offset"]
        page = visible[offset:offset + limit]
        has_more = offset + limit < len(visible)

        return 200, {"payments": [serialize_payment(p) for p in page], "has_more": has_more}


def register(router) -> None:
    router.add("GET", "/activity", ActivityEndpoint())
