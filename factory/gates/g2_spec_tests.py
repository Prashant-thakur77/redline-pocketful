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
              and e.payload.get("gate") == "g2" and e.payload.get("passed") and not e.payload.get("scoped")]
    return max(counts, default=0)


def check(gate: Gate, base_url: str) -> int:
    tests = gate.stage_dir / "tests"
    if not tests.is_dir():
        return gate.finish(False, "tests/ is missing; tests come before code")
    reqs = getattr(gate, "reqs", "")
    if reqs:  # an item checked against its own requirements; the stage close runs everything
        counts = run_pytest([tests], base_url, gate, extra=["-p", "factory.gates.reqfilter", "--req", reqs])
        summary = (f"{counts['passed']} passed, {counts['failures']} failed for {reqs} "
                   f"({counts['errors']} errors, {counts['skipped']} skipped)")
        return gate.finish(green(counts), summary, counts=counts, scoped=reqs)
    high = previous_high(gate)
    counts = run_pytest([tests], base_url, gate, timeout=gate.timeout)
    summary = (f"{counts['passed']} passed, {counts['failures']} failed, "
               f"{counts['errors']} errors, {counts['skipped']} skipped")
    if counts.get("timed_out"):  # no report was written: say so, never call it a removed test
        return gate.finish(False, f"the suite did not finish within {gate.timeout:.0f}s (raise --timeout); "
                                  f"no test was removed", counts=counts)
    if counts["tests"] < high:
        return gate.finish(False, f"only {counts['tests']} tests collected, {high} passed before: "
                                  f"a test was removed — {summary}", counts=counts)
    return gate.finish(green(counts), summary, counts=counts)


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--req", default="", help="only tests naming these requirement ids (comma-separated)")
    parser.add_argument("--timeout", type=float, default=2400, help="seconds the whole suite may take")
    args = parser.parse_args(argv)
    gate = Gate("g2", args)
    gate.timeout = args.timeout
    gate.reqs = args.req
    return run_gate(gate, args, lambda url: check(gate, url))


if __name__ == "__main__":
    raise SystemExit(main())
