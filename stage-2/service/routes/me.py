"""GET /me — R-1-120."""
from __future__ import annotations

from ..pipeline import Endpoint, RequestCtx
from ..store import STORE


class MeEndpoint(Endpoint):
    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user = ctx.user
        balance = STORE.wallets.get(user["id"], 0)
        return 200, {
            "user_id": user["id"],
            "display_name": user["display_name"],
            "handle": user["handle"],
            "balance": balance,
            "currency": STORE.currency,
            "minor_units": STORE.minor_units,
        }


def register(router) -> None:
    router.add("GET", "/me", MeEndpoint())
