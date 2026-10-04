"""The shared error-precedence chain, implemented once (R-1-075).

    1. 401 unauthenticated
    2. endpoint-level permission not depending on the body -> 403
    3. 400 malformed_request for an unparseable/non-object body
    4. 400 missing_idempotency_key
    5. 422 validation_failed for an over-long Idempotency-Key
    6. idempotency resolution -> replay (same status/body) or 409
    7. endpoint field validation -> 422 (R-1-076 fixes the sub-order)
    8. resource lookup -> 404
    9. permission on the looked-up resource -> 403
    10. resource-state checks -> 409
    11. funds check, performed inside the store's write lock together with
        the apply, so the check and the mutation are one atomic step.

Every later endpoint (payments, requests, splits, settlements) subclasses
`Endpoint` and only fills in the hooks that need business logic; steps
1, 3, 4, 5 and 6 are enforced here exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import auth
from .idempotency import IDEMPOTENCY
from .json_utils import parse_json_object
from .store import STORE
from .validation import validate_idempotency_key


@dataclass
class RequestCtx:
    method: str
    path: str
    raw_body: bytes
    headers: dict  # lower-cased header names
    query: dict
    path_params: dict
    user: dict | None = None
    body: dict = field(default_factory=dict)


class Endpoint:
    requires_auth: bool = True
    has_body: bool = False          # True for POST/PUT endpoints that read a JSON body
    requires_idempotency_key: bool = False

    def check_permission(self, ctx: RequestCtx) -> None:
        """Step 2: permission that does not depend on the parsed body."""
        return None

    def validate_fields(self, ctx: RequestCtx) -> dict:
        """Step 7: return the validated/parsed fields, or raise ApiError."""
        return {}

    def lookup(self, ctx: RequestCtx, fields: dict) -> Any:
        """Step 8: return the target resource, or raise not_found."""
        return None

    def check_resource_permission(self, ctx: RequestCtx, resource: Any, fields: dict) -> None:
        """Step 9."""
        return None

    def check_resource_state(self, ctx: RequestCtx, resource: Any, fields: dict) -> None:
        """Step 10."""
        return None

    def apply(self, ctx: RequestCtx, resource: Any, fields: dict) -> tuple[int, dict]:
        """Step 11: funds check + mutation, called with the store's write
        lock already held. Must return (status, body)."""
        raise NotImplementedError

    def handle(self, ctx: RequestCtx) -> tuple[int, dict]:
        if self.requires_auth:
            ctx.user = auth.authenticate(STORE, ctx.headers.get("authorization"))

        self.check_permission(ctx)

        if self.has_body:
            ctx.body = parse_json_object(ctx.raw_body)

        composite = None
        if self.requires_idempotency_key:
            idem_key = validate_idempotency_key(ctx.headers.get("idempotency-key"))
            outcome, payload = IDEMPOTENCY.resolve_or_claim(ctx.user["id"], ctx.method, ctx.path,
                                                              idem_key, ctx.body)
            if outcome == "replay":
                return payload
            composite = payload  # this call is the one that must run the operation

        try:
            fields = self.validate_fields(ctx)
            resource = self.lookup(ctx, fields)
            self.check_resource_permission(ctx, resource, fields)
            self.check_resource_state(ctx, resource, fields)

            with STORE.write_lock():
                status, body = self.apply(ctx, resource, fields)
        except Exception:
            # R-1-107: never leave a claimed key behind a failed attempt —
            # the next use, with any body, is a genuine first use.
            if composite is not None:
                IDEMPOTENCY.release(composite)
            raise

        if composite is not None:
            IDEMPOTENCY.commit(composite, status, body)
        return status, body
