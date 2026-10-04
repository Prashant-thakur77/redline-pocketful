"""Ledger event schema. Adapted from Freight Room's RoomEventSchema.

Every event names where it came from (`source`), so any figure in a report can
be traced back to a room message, a gate log or a seat's cost record.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

Kind = Literal["handoff", "verdict", "gate_result", "cost", "stage_closed"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Event(BaseModel):
    kind: Kind
    ts: str = Field(default_factory=now)
    seat: str | None = None
    stage: int | None = None
    node: str | None = None
    source: str  # e.g. "room:<message id>", "gate:g2", "seat:builder"
    payload: dict[str, Any] = {}
    prev: str | None = None
    hash: str | None = None
