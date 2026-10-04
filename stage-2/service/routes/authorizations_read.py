"""GET /authorizations — R-2-004, R-2-030, R-2-031.

Create/capture/void are N2-2/N2-3's scope; this exists now because
status and the captured/open distinction must be derived at read time
(R-2-030), and the fixture-validation tests (R-2-021..028) plus the
storm's own R-2-004 check need a way to read back what reset seeded,
filtered by direction and status exactly like GET /requests.
"""
from __future__ import annotations

import time

from ..errors import validation_failed
from ..holds import effective_status, remaining_amount
from ..json_utils import epoch_to_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE
from ..validation import parse_limit, parse_offset

_VALID_DIRECTIONS = {"incoming", "outgoing"}
_VALID_STATUSES = {"open", "captured", "voided", "expired"}


class AuthorizationsListEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        direction = ctx.query.get("direction")
        if direction is not None and direction not in _VALID_DIRECTIONS:
            raise validation_failed('direction must be "incoming" or "outgoing"')
        status = ctx.query.get("status")
        if status is not None and status not in _VALID_STATUSES:
            raise validation_failed("status must be one of open/captured/voided/expired")
        return {
            "limit": parse_limit(ctx.query.get("limit")),
            "offset": parse_offset(ctx.query.get("offset")),
            "direction": direction,
            "status": status,
        }

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user_id = ctx.user["id"]
        now = time.time()
        direction, status = fields["direction"], fields["status"]

        visible = []
        for a in STORE.authorizations.values():
            is_from = a["from_user_id"] == user_id
            is_to = a["to_user_id"] == user_id
            if not (is_from or is_to):
                continue
            if direction == "outgoing" and not is_from:
                continue
            if direction == "incoming" and not is_to:
                continue
            if status is not None and effective_status(a, now) != status:
                continue
            visible.append(a)
        visible.sort(key=lambda a: a["seq"], reverse=True)

        limit, offset = fields["limit"], fields["offset"]
        page = visible[offset:offset + limit]
        has_more = offset + limit < len(visible)

        out = [_serialize(a, now) for a in page]
        return 200, {"authorizations": out, "has_more": has_more}


def _serialize(a: dict, now: float) -> dict:
    from_user = STORE.users_by_id.get(a["from_user_id"])
    to_user = STORE.users_by_id.get(a["to_user_id"])
    status = effective_status(a, now)
    return {
        "authorization_id": a["id"],
        "from_user_id": a["from_user_id"],
        "from_handle": from_user["handle"] if from_user else None,
        "to_user_id": a["to_user_id"],
        "to_handle": to_user["handle"] if to_user else None,
        "amount": a["amount"],
        "currency": STORE.currency,
        "note": a["note"],
        "visibility": a["visibility"],
        # R-2-030: status is derived from the clock on every read, never
        # taken verbatim from the stored field.
        "status": status,
        "captured_amount": a.get("captured_amount", 0),
        "remaining_amount": remaining_amount(a) if status == "open" else 0,
        "payment_ids": list(a.get("payment_ids", [])),
        "created_at": a["created_at"],
        "expires_at": epoch_to_rfc3339(a["expires_at"]),
    }


def register(router) -> None:
    router.add("GET", "/authorizations", AuthorizationsListEndpoint())
