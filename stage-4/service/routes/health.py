"""GET /health — R-1-014, R-1-089 (no auth required)."""
from __future__ import annotations

from ..pipeline import Endpoint, RequestCtx


class HealthEndpoint(Endpoint):
    requires_auth = False

    def apply(self, ctx: RequestCtx, resource, fields):
        return 200, {"status": "ok"}


def register(router) -> None:
    router.add("GET", "/health", HealthEndpoint())
