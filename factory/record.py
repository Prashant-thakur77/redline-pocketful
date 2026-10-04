"""`python -m factory.record <kind> …` — a seat writes one ledger event.

    dispatch      --stage N --node ID [--to SEAT …] [--text …]      (planner)
    verdict       --stage N --node ID --verdict V --text …          (verifier, adversary)
    cost          --stage N [--node ID] --tokens T --usd U --seconds S --seat SEAT
    stage_closed  --stage N --result closed|partial|blocked         (planner)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from factory.events import Event
from factory.ledger import Ledger
from factory.protocol import Verdict

DEFAULT_SEAT = {"dispatch": "planner", "verdict": "verifier", "stage_closed": "planner"}
KIND = {"dispatch": "handoff", "verdict": "verdict", "cost": "cost", "stage_closed": "stage_closed"}


def evidence_dir() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    return (Path(proc.stdout.strip()) if proc.returncode == 0 else Path.cwd()) / "evidence"


def head() -> str | None:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


REQUIRED_FOR_GO = {"g1", "g2"}


def go_blockers(events, stage: int, node: str, commit: str | None) -> list[str]:
    """A GO is a fact about gate results, not an opinion: the latest run of every gate on
    this item at this commit must have passed, and gates 1 and 2 must be among them."""
    runs = [e for e in events if e.kind == "gate_result" and e.stage == stage and e.node == node
            and (not commit or str(e.payload.get("commit", "")).startswith(commit[:7]))]
    latest = {e.payload.get("gate"): e for e in runs}
    problems = [f"gate {g} has no result for this item at this commit" for g in sorted(REQUIRED_FOR_GO - set(latest))]
    problems += [f"gate {g} last failed: {e.payload.get('detail', '')[:120]}" for g, e in sorted(latest.items())
                 if not e.payload.get("passed")]
    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=list(KIND))
    parser.add_argument("--stage", type=int, required=True)
    parser.add_argument("--node")
    parser.add_argument("--seat")
    parser.add_argument("--to", nargs="*", default=[])
    parser.add_argument("--verdict", choices=list(Verdict.__args__))
    parser.add_argument("--text", default="")
    parser.add_argument("--result")
    parser.add_argument("--commit", help="the commit judged (default: HEAD)")
    parser.add_argument("--tokens", type=int, default=0)
    parser.add_argument("--usd", type=float, default=0.0)
    parser.add_argument("--seconds", type=float, default=0.0)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args(argv)

    seat = args.seat or DEFAULT_SEAT.get(args.what)
    if not seat:
        parser.error("--seat is required for this kind")
    if args.what in ("dispatch", "verdict") and not args.node:
        parser.error("--node is required")
    if args.what == "verdict" and not args.verdict:
        parser.error("--verdict is required")
    if args.what == "verdict" and args.verdict == "GO":
        events = Ledger((args.evidence or evidence_dir()) / "ledger.jsonl").events()
        blockers = go_blockers(events, args.stage, args.node, args.commit or head())
        if blockers:
            print("refusing GO: " + "; ".join(blockers) + ". Record NEEDS_WORK instead.", file=sys.stderr)
            return 1
    payload = {
        "dispatch": lambda: {"to": args.to, "text": args.text, "dispatch": True},
        "verdict": lambda: {"verdict": args.verdict, "text": args.text, "to": args.to,
                             "commit": args.commit or head()},
        "cost": lambda: {"tokens": args.tokens, "usd": args.usd, "seconds": args.seconds},
        "stage_closed": lambda: {"result": args.result or "closed", "text": args.text},
    }[args.what]()
    event = Ledger((args.evidence or evidence_dir()) / "ledger.jsonl").append(Event(
        kind=KIND[args.what], seat=seat, stage=args.stage, node=args.node,
        source=f"seat:{seat}", payload=payload))
    print(f"recorded {event.kind} {event.hash[:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
