"""POST /_test/reset (R-1-040..050), GET /_test/export, POST /_test/import
(R-1-200..210)."""
from __future__ import annotations

from ..fixtures import validate_fixture
from ..pipeline import Endpoint, RequestCtx
from ..snapshot import export_state, validate_import_document
from ..store import STORE


class ResetEndpoint(Endpoint):
    requires_auth = False
    has_body = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        return validate_fixture(ctx.body)

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        STORE.apply_reset(fields)
        return 204, None


class ExportEndpoint(Endpoint):
    requires_auth = False

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        # R-1-208: export is an atomic, read-only snapshot — apply() always
        # runs under STORE.write_lock(), so nothing can land mid-serialization.
        return 200, export_state(STORE)


class ImportEndpoint(Endpoint):
    requires_auth = False
    has_body = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        return validate_import_document(ctx.body)

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        STORE.apply_import(fields)
        return 204, None


def register(router) -> None:
    router.add("POST", "/_test/reset", ResetEndpoint())
    router.add("GET", "/_test/export", ExportEndpoint())
    router.add("POST", "/_test/import", ImportEndpoint())
