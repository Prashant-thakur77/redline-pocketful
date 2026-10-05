"""GET /me — R-1-120, R-2-010, R-2-011, R-3-020..027."""
from __future__ import annotations

from ..errors import validation_failed
from ..holds import held_for
from ..json_utils import parse_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import balance_for_view
from ..store import STORE


def _parse_optional_instant(raw: str | None, field_name: str) -> float | None:
    # R-3-020/075: must be a real RFC 3339 instant with an explicit
    # offset; a naive local time, a bare date or anything else is 422,
    # the same discipline every other timestamp field uses.
    if raw is None:
        return None
    try:
        return parse_rfc3339(raw)
    except (ValueError, TypeError):
        raise validation_failed(f"{field_name} must be an RFC 3339 timestamp with an explicit offset")


class MeEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        as_of_raw = ctx.query.get("as_of")
        known_at_raw = ctx.query.get("known_at")
        return {
            "as_of_raw": as_of_raw, "as_of_epoch": _parse_optional_instant(as_of_raw, "as_of"),
            "known_at_raw": known_at_raw, "known_at_epoch": _parse_optional_instant(known_at_raw, "known_at"),
        }

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user = ctx.user
        held = held_for(STORE, user["id"])
        if fields["as_of_epoch"] is None and fields["known_at_epoch"] is None:
            # R-3-021/072: no temporal parameter keeps the existing shape
            # and the current, fully-corrected balance — stage-2
            # behaviour does not shift.
            total = STORE.wallets.get(user["id"], 0)
        else:
            total = balance_for_view(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                      user["id"], as_of_epoch=fields["as_of_epoch"],
                                      known_at_epoch=fields["known_at_epoch"])
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
        # R-3-025/076: echoed back exactly as given, byte for byte — never
        # normalized (e.g. "Z" rewritten to "+00:00").
        if fields["as_of_raw"] is not None:
            body["as_of"] = fields["as_of_raw"]
        if fields["known_at_raw"] is not None:
            body["known_at"] = fields["known_at_raw"]
        return 200, body


def register(router) -> None:
    router.add("GET", "/me", MeEndpoint())
