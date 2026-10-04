"""Registers every route on the shared router. Later items add their own
module here and call its `register()`; this item only wires /health."""
from __future__ import annotations

from ..server import ROUTER
from . import activity, auth, health, me, payments, requests, requests_read, test_control


def register_all() -> None:
    health.register(ROUTER)
    test_control.register(ROUTER)
    auth.register(ROUTER)
    me.register(ROUTER)
    requests_read.register(ROUTER)
    requests.register(ROUTER)
    payments.register(ROUTER)
    activity.register(ROUTER)
