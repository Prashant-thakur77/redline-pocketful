"""Bearer-token authentication (R-1-063). Signup/login land in N1-3; this
item only provides the lookup every endpoint's precedence step 1 uses."""
from __future__ import annotations

from .errors import unauthenticated
from .store import Store

_BEARER_PREFIX = "Bearer "


def authenticate(store: Store, authorization_header: str | None) -> dict:
    """Return the caller's user record, or raise 401 unauthenticated."""
    if not authorization_header or not authorization_header.startswith(_BEARER_PREFIX):
        raise unauthenticated()
    token = authorization_header[len(_BEARER_PREFIX):]
    if not token:
        raise unauthenticated()
    user_id = store.tokens.get(token)
    if user_id is None:
        raise unauthenticated()
    user = store.users_by_id.get(user_id)
    if user is None:
        raise unauthenticated()
    return user
