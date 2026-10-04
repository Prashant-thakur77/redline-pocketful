"""POST /_test/reset — R-1-040..050."""
from __future__ import annotations

from ..fixtures import validate_fixture
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE


class ResetEndpoint(Endpoint):
    requires_auth = False
    has_body = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        return validate_fixture(ctx.body)

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        STORE.apply_reset(fields)
        return 204, None


def register(router) -> None:
    router.add("POST", "/_test/reset", ResetEndpoint())
