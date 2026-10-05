"""The one place every SSR page calls a real endpoint object for a read —
same R-2-185 discipline writes already follow, applied to GETs too, so
no page here ever re-derives `held`, re-filters a feed, or re-applies a
direction/status rule a JSON endpoint already owns.
"""
from __future__ import annotations

from ..pipeline import RequestCtx


def call_authed(endpoint, method: str, path: str, token: str, query: dict | None = None,
                 path_params: dict | None = None):
    ctx = RequestCtx(method=method, path=path, raw_body=b"", headers={"authorization": f"Bearer {token}"},
                      query=query or {}, path_params=path_params or {})
    return endpoint.handle(ctx)
