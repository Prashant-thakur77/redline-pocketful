"""POST /auth/login, POST /auth/signup — R-1-034, R-1-036, R-1-037,
R-1-080..092."""
from __future__ import annotations

import secrets

from ..errors import email_taken, handle_taken, malformed_request, unauthenticated, validation_failed
from ..handles import derive_handle
from ..passwords import DUMMY_PASSWORD_HASH, hash_password, verify_password
from ..pipeline import Endpoint, RequestCtx
from ..store import STORE

_MIN_PASSWORD_LEN = 8


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
        # Always pay the same PBKDF2 cost whether or not the email exists —
        # short-circuiting on `user is None` would let wall-clock timing
        # distinguish the two cases even though both return the same 401.
        hash_to_check = user["password_hash"] if user is not None else DUMMY_PASSWORD_HASH
        password_ok = verify_password(fields["password"], hash_to_check)
        if user is None or not password_ok:
            # R-1-086: unknown email and wrong password are indistinguishable.
            raise unauthenticated()
        token = secrets.token_urlsafe(32)
        STORE.tokens[token] = user["id"]
        return 200, {"user_id": user["id"], "display_name": user["display_name"], "token": token}


class SignupEndpoint(Endpoint):
    requires_auth = False
    has_body = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "email" not in body or "password" not in body or "display_name" not in body:
            raise validation_failed("email, password and display_name are required")
        email, password, display_name = body["email"], body["password"], body["display_name"]
        if not isinstance(email, str):
            raise malformed_request("email must be a string")
        if not isinstance(password, str):
            raise malformed_request("password must be a string")
        if not isinstance(display_name, str):
            raise malformed_request("display_name must be a string")

        # R-1-085: local@domain, both parts non-empty; only the first "@" splits.
        if "@" not in email:
            raise validation_failed("email must be of the form local@domain")
        local, domain = email.split("@", 1)
        if not local or not domain:
            raise validation_failed("email must be of the form local@domain")

        if len(password) < _MIN_PASSWORD_LEN:
            raise validation_failed(f"password must be at least {_MIN_PASSWORD_LEN} characters")

        return {"email": email, "password": password, "display_name": display_name}

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        user_id, token = create_user(fields["email"], fields["password"], fields["display_name"])
        user = STORE.users_by_id[user_id]
        return 201, {"user_id": user_id, "display_name": user["display_name"], "token": token}


def create_user(email: str, password: str, display_name: str) -> tuple[str, str]:
    """The check-then-insert every signup path needs, factored out so the
    UI's `POST /signup` form (`service/ui/pages.py`) can share it instead
    of reimplementing it — a second copy is exactly how R-1-088's
    exactly-one-winner guarantee drifted out from under the form path
    (adversary's BREACH on N2-5). Must be called with `STORE.write_lock()`
    already held: R-1-088 requires email_taken-then-handle_taken-then-
    insert to run as one atomic step, or two concurrent signups racing on
    the same email/derived handle can both read "not taken" before either
    writes, producing two 201s instead of one 201 and one 409."""
    if email in STORE.users_by_email:
        raise email_taken()

    handle = derive_handle(email)  # non-empty: caller validates local-part non-empty first
    if handle in STORE.users_by_handle:
        raise handle_taken()

    user_id = secrets.token_urlsafe(16)
    user = {
        "id": user_id,
        "email": email,
        "password_hash": hash_password(password),
        "display_name": display_name,
        "handle": handle,
        "balance": 0,
    }
    STORE.users_by_id[user_id] = user
    STORE.users_by_handle[handle] = user_id
    STORE.users_by_email[email] = user
    STORE.wallets[user_id] = 0

    token = secrets.token_urlsafe(32)
    STORE.tokens[token] = user_id
    return user_id, token


def register(router) -> None:
    router.add("POST", "/auth/login", LoginEndpoint())
    router.add("POST", "/auth/signup", SignupEndpoint())
