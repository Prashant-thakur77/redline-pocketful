"""Registers every route on the shared router. Later items add their own
module here and call its `register()`; this item only wires /health."""
from __future__ import annotations

from ..server import ROUTER
from . import health


def register_all() -> None:
    health.register(ROUTER)
