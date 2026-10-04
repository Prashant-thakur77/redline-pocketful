"""POST /auth/login — R-1-082, R-1-086, R-1-090, R-1-092. Signup is N1-3."""
from __future__ import annotations

import secrets

from ..errors import malformed_request, unauthenticated, validation_failed
from ..passwords import verify_password
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE


class LoginEndpoint(Endpoint):
    requires_auth = False
    has_body = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "email" not in body or "password" not in body:
            raise validation_failed("email and password are required")
        email, password = body["email"], body["password"]
        if not isinstance(email, str):
            raise malformed_request("email must be a string")
        if not isinstance(password, str):
            raise malformed_request("password must be a string")
        return {"email": email, "password": password}

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user = STORE.users_by_email.get(fields["email"])
        if user is None or not verify_password(fields["password"], user["password_hash"]):
            # R-1-086: unknown email and wrong password are indistinguishable.
            raise unauthenticated()
        token = secrets.token_urlsafe(32)
        STORE.tokens[token] = user["id"]
        return 200, {"user_id": user["id"], "display_name": user["display_name"], "token": token}


def register(router) -> None:
    router.add("POST", "/auth/login", LoginEndpoint())
