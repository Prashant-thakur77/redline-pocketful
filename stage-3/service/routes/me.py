"""GET /me — R-1-120, R-2-010, R-2-011, R-3-020..027."""
from __future__ import annotations

from ..errors import validation_failed
from ..holds import held_for
from ..json_utils import parse_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import balance_as_of
from ..store import STORE


class MeEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        as_of_raw = ctx.query.get("as_of")
        if as_of_raw is None:
            return {"as_of_raw": None, "as_of_epoch": None}
        # R-3-020: must be a real RFC 3339 instant with an explicit
        # offset; a naive local time, a bare date or anything else is
        # 422, the same discipline every other timestamp field uses.
        try:
            as_of_epoch = parse_rfc3339(as_of_raw)
        except (ValueError, TypeError):
            raise validation_failed("as_of must be an RFC 3339 timestamp with an explicit offset")
        return {"as_of_raw": as_of_raw, "as_of_epoch": as_of_epoch}

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user = ctx.user
        held = held_for(STORE, user["id"])
        if fields["as_of_epoch"] is None:
            # R-3-021: no temporal parameter keeps the existing shape and
            # the current, fully-corrected balance — stage-2 behaviour
            # does not shift.
            total = STORE.wallets.get(user["id"], 0)
        else:
            total = balance_as_of(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                   user["id"], fields["as_of_epoch"])
        body = {
            "user_id": user["id"],
            "display_name": user["display_name"],
            "handle": user["handle"],
            "balance": total,
            "total": total,
            "available": total - held,
            "held": held,
            "currency": STORE.currency,
            "minor_units": STORE.minor_units,
        }
        if fields["as_of_raw"] is not None:
            # R-3-025: echoed back exactly as given, byte for byte —
            # never normalized (e.g. "Z" rewritten to "+00:00").
            body["as_of"] = fields["as_of_raw"]
        return 200, body


def register(router) -> None:
    router.add("GET", "/me", MeEndpoint())
