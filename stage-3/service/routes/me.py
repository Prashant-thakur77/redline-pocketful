"""GET /me — R-1-120, R-2-010, R-2-011."""
from __future__ import annotations

from ..holds import held_for
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE


class MeEndpoint(Endpoint):
    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user = ctx.user
        total = STORE.wallets.get(user["id"], 0)
        held = held_for(STORE, user["id"])
        return 200, {
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


def register(router) -> None:
    router.add("GET", "/me", MeEndpoint())
