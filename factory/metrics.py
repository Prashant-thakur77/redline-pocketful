"""Numbers derived from ledger events. Each figure keeps the sources it came from.

Payload conventions:
  cost         {tokens, usd, seconds}
  gate_result  {gate, passed, log, detail?, commit?}
  handoff      {evidence?, to: [seat], text?}
  verdict      {verdict, evidence?, to: [seat], text?}
  stage_closed {result, ...}
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from factory.events import Event

REJECTIONS = {"NEEDS_WORK", "BLOCK", "BREACH"}
ACCEPTED = {"GO", "HOLDS"}  # an item closes on GO, or on HOLDS while a stage-level gate is still advisory


@dataclass
class Figure:
    value: float = 0
    sources: list[str] = field(default_factory=list)

    def add(self, amount: float, source: str):
        self.value += amount
        self.sources.append(source)


def for_stage(events: list[Event], stage: int | None) -> list[Event]:
    return [e for e in events if stage is None or e.stage == stage]


def cost_by_seat(events: list[Event]) -> dict[str, dict[str, Figure]]:
    sheet: dict[str, dict[str, Figure]] = defaultdict(lambda: defaultdict(Figure))
    for e in events:
        if e.kind != "cost":
            continue
        for metric in ("tokens", "usd", "seconds"):
            sheet[e.seat or "?"][metric].add(float(e.payload.get(metric, 0) or 0), e.source)
    return sheet


def verdict_of(e: Event) -> str | None:
    if e.kind != "verdict":
        return None
    return e.payload.get("verdict") or (e.payload.get("evidence") or {}).get("verdict")


def chronological(events: list[Event]) -> list[Event]:
    """Room events are ingested after the run, so file order is not time order."""
    return sorted(events, key=lambda e: e.ts)


def item_of(node: str) -> str:
    """The work item a node belongs to: a fix item ("N2-4B"), an attack ("N2-4A") or a re-plan
    ("N2-6'") counts toward the item it came from."""
    return re.sub(r"(?<=\d)[A-Z]?['′]*$", "", node)


def rejections(events: list[Event]) -> list[dict]:
    """Each NEEDS_WORK/BLOCK/BREACH, and whether its item was later accepted (GO or HOLDS)."""
    rows = []
    events = chronological(events)
    for i, e in enumerate(events):
        verdict = verdict_of(e)
        if verdict not in REJECTIONS:
            continue
        recovered = None if e.node is None else next(
            (later for later in events[i + 1:]
             if later.node is not None and item_of(later.node) == item_of(e.node) and later.stage == e.stage
             and verdict_of(later) in ACCEPTED), None)
        rows.append({"stage": e.stage, "node": e.node, "seat": e.seat, "verdict": verdict,
                     "what": (e.payload.get("text") or e.payload.get("detail") or "")[:200],
                     "to": e.payload.get("to", []), "source": e.source, "commit": e.payload.get("commit"),
                     "recovered_by": recovered.source if recovered else None,
                     "fixed_commit": recovered.payload.get("commit") if recovered else None})
    return rows


def gate_sheet(events: list[Event]) -> dict[str, dict]:
    """Per gate: runs, failures caught, and the latest result."""
    sheet: dict[str, dict] = {}
    for e in events:
        if e.kind != "gate_result":
            continue
        gate = e.payload.get("gate", "?")
        row = sheet.setdefault(gate, {"runs": 0, "failures": 0, "last": None, "sources": []})
        row["runs"] += 1
        row["failures"] += 0 if e.payload.get("passed") else 1
        row["last"] = "pass" if e.payload.get("passed") else "fail"
        row["sources"].append(e.source)
    return dict(sorted(sheet.items()))


def catch_rate(events: list[Event]) -> Figure:
    """Share of reviewed nodes that were rejected at least once before closing."""
    reviewed, rejected = set(), set()
    sources = []
    for e in events:
        verdict = verdict_of(e)
        if verdict is None or e.node is None:
            continue
        reviewed.add((e.stage, e.node))
        if verdict in REJECTIONS:
            rejected.add((e.stage, e.node))
            sources.append(e.source)
    return Figure(round(len(rejected) / len(reviewed), 3) if reviewed else 0.0, sources)


def wall_seconds(events: list[Event]) -> float:
    from datetime import datetime

    stamps = [datetime.fromisoformat(e.ts) for e in events]
    return (max(stamps) - min(stamps)).total_seconds() if len(stamps) > 1 else 0.0


def with_inferred_stages(events: list[Event]) -> list[Event]:
    """Measured costs carry no stage; give each the stage the band was working on at that
    moment (the stage of the latest staged event before it)."""
    out, current = [], None
    for e in chronological(events):
        if e.kind != "cost" and e.stage is not None:
            current = e.stage
        if e.kind == "cost" and e.stage is None and current is not None:
            e = e.model_copy(update={"stage": current})
        out.append(e)
    return out


def measured_only(events: list[Event]) -> list[Event]:
    """When the runtime measured spend (seat logs, usage events), drop the seats' own
    estimates so no cost is counted twice or guessed."""
    measured = any(e.kind == "cost" and (e.source.startswith("log:") or "usage" in e.payload) for e in events)
    if not measured:
        return events
    return [e for e in events if not (e.kind == "cost" and not (e.source.startswith("log:") or "usage" in e.payload))]
