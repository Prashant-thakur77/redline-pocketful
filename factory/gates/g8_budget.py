"""Gate 8 — budget governor: the work item and its stage are within their caps
(attempts, wall time, tokens, spend). When a cap trips, the item goes back to
the planner with this log; it never comes to a human."""
from __future__ import annotations

from pathlib import Path

from factory import governor
from factory.gates.common import Gate, base_parser
from factory.ledger import Ledger


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--caps", type=Path, default=governor.CAPS)
    args = parser.parse_args(argv)
    gate = Gate("g8", args)
    events = Ledger(gate.evidence / "ledger.jsonl").events()
    found = governor.trips(events, gate.stage, args.node, governor.load_caps(args.caps))
    gate.log(*(found or ["within caps"]))
    detail = "; ".join(found) + " — return the item to @planner" if found else "within caps"
    return gate.finish(not found, detail, trips=found)


if __name__ == "__main__":
    raise SystemExit(main())
