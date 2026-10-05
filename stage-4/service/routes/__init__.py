"""Registers every route on the shared router. Later items add their own
module here and call its `register()`; this item only wires /health."""
from __future__ import annotations

from ..server import ROUTER
from . import (activity, auth, authorization_actions, authorizations, authorizations_read,
               correction_batches, corrections, health, me, payments, refunds, requests,
               requests_read, revisions, settlements, splits, statement, test_control)


def register_all() -> None:
    health.register(ROUTER)
    test_control.register(ROUTER)
    auth.register(ROUTER)
    me.register(ROUTER)
    requests_read.register(ROUTER)
    requests.register(ROUTER)
    payments.register(ROUTER)
    activity.register(ROUTER)
    splits.register(ROUTER)
    settlements.register(ROUTER)
    authorizations_read.register(ROUTER)
    authorizations.register(ROUTER)
    authorization_actions.register(ROUTER)
    revisions.register(ROUTER)
    statement.register(ROUTER)
    corrections.register(ROUTER)
    refunds.register(ROUTER)
    correction_batches.register(ROUTER)
