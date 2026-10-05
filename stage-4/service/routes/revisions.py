"""GET /payments/{id}/revisions — R-3-063, R-3-064, R-3-078.

No temporal query parameters are defined here: R-3-078 is explicit that
`known_at`/`as_of` on this endpoint are simply unknown parameters, ignored
under R-1-023, never a filter. The endpoint is a record of what was
recorded; it always returns the complete history.
"""
from __future__ import annotations

from ..errors import not_found
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE


class PaymentRevisionsEndpoint(Endpoint):
    def lookup(self, ctx: RequestCtx, fields: dict):
        payment = STORE.payments.get(ctx.path_params.get("id"))
        if payment is None:
            raise not_found("no such payment")
        return payment

    def check_resource_permission(self, ctx: RequestCtx, resource, fields: dict) -> None:
        # R-3-064: only the two parties may read this — a third party
        # (even for a public payment) gets 404, not 403; this endpoint
        # names no 403 exception to R-1-078's general hide-as-404 rule.
        user_id = ctx.user["id"]
        if resource["from_user_id"] != user_id and resource["to_user_id"] != user_id:
            raise not_found("no such payment")

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        revisions = STORE.payment_revisions.get(resource["id"], [])
        return 200, {"revisions": list(revisions)}


def register(router) -> None:
    router.add("GET", "/payments/{id}/revisions", PaymentRevisionsEndpoint())
