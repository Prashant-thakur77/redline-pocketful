"""Gate 2 — spec tests: every test in the folder's `tests/` passes against the
running service. Zero tests, skips and errors fail. The number of collected
tests may never drop below the highest count recorded for this stage or an
earlier one (stages are copied forward, so their tests come along)."""
from __future__ import annotations

from factory.gates.common import Gate, base_parser, run_gate, green, run_pytest
from factory.ledger import Ledger


def previous_high(gate: Gate) -> int:
    counts = [e.payload.get("counts", {}).get("tests", 0) for e in Ledger(gate.evidence / "ledger.jsonl").events()
              if e.kind == "gate_result" and e.stage is not None and e.stage <= (gate.stage or 0)
              and e.payload.get("gate") == "g2" and e.payload.get("passed")]
    return max(counts, default=0)


def check(gate: Gate, base_url: str) -> int:
    tests = gate.stage_dir / "tests"
    if not tests.is_dir():
        return gate.finish(False, "tests/ is missing; tests come before code")
    high = previous_high(gate)
    counts = run_pytest([tests], base_url, gate)
    summary = (f"{counts['passed']} passed, {counts['failures']} failed, "
               f"{counts['errors']} errors, {counts['skipped']} skipped")
    if counts["tests"] < high:
        return gate.finish(False, f"only {counts['tests']} tests collected, {high} passed before: "
                                  f"a test was removed — {summary}", counts=counts)
    return gate.finish(green(counts), summary, counts=counts)


def main(argv=None) -> int:
    args = base_parser(__doc__).parse_args(argv)
    gate = Gate("g2", args)
    return run_gate(gate, args, lambda url: check(gate, url))


if __name__ == "__main__":
    raise SystemExit(main())
