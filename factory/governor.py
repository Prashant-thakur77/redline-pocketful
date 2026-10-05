"""Budget governor: per-item and per-stage caps on attempts, wall time, tokens
and spend, read from the ledger. A trip is gate 8 failing; the planner then
descopes or re-plans the item. No cap ever routes to a human."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from factory import ROOT
from factory.events import Event
from factory.metrics import REJECTIONS, verdict_of

CAPS = ROOT / "budget.yaml"


def load_caps(path: Path | str = CAPS) -> dict:
    return yaml.safe_load(Path(path).read_text())


def _minutes_since(events: list[Event], now: datetime) -> float:
    if not events:
        return 0.0
    first = min(datetime.fromisoformat(e.ts) for e in events)
    return (now - first).total_seconds() / 60


def _spend(events: list[Event], key: str) -> float:
    return sum(float(e.payload.get(key, 0) or 0) for e in events if e.kind == "cost")


def trips(events: list[Event], stage: int | None, node: str | None, caps: dict,
          now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    found = []
    staged = [e for e in events if e.stage == stage]
    if node and node != "close":
        mine = [e for e in staged if e.node == node]
        cap = caps.get("node", {})
        # one attempt per rejected commit: re-checking the same commit is not another attempt
        attempts = len({str(e.payload.get("commit"))[:7] if e.payload.get("commit") else (e.hash or e.ts)
                        for e in mine if verdict_of(e) in REJECTIONS})
        checks = [("attempts", attempts), ("minutes", _minutes_since(mine, now)),
                  ("tokens", _spend(mine, "tokens")), ("usd", _spend(mine, "usd"))]
        found += [f"item {node}: {name} {value:,.1f} > cap {cap[name]}" for name, value in checks
                  if name in cap and value > cap[name]]
    cap = caps.get("stage", {})
    checks = [("minutes", _minutes_since(staged, now)), ("usd", _spend(staged, "usd"))]
    found += [f"stage: {name} {value:,.1f} > cap {cap[name]}" for name, value in checks
              if name in cap and value > cap[name]]
    return found


def main(argv=None) -> int:
    """`python -m factory.governor check --stage N --node ID` — gate 8 from the repo root."""
    import argparse

    from factory.gates import g8_budget

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--node", required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    return g8_budget.main([str(args.repo / f"stage-{args.stage}"), "--stage", str(args.stage),
                           "--node", args.node, "--evidence", str(args.repo / "evidence")])


if __name__ == "__main__":
    raise SystemExit(main())
