"""Gate 3 — public checks: the task package's own harness, run the way judges
run it (isolated). One gate among eight, never the target: it records only
pass/fail, the claimed stage and the log path."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from factory.gates.common import Gate, base_parser, run


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--track", required=True, help="track name the harness knows")
    parser.add_argument("--kickoff", type=Path, required=True, help="task package checkout")
    parser.add_argument("--mode", default="isolated", choices=("isolated", "host"))
    args = parser.parse_args(argv)
    gate = Gate("g3", args)
    kickoff = args.kickoff.resolve()
    python = kickoff / ".venv" / "bin" / "python"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = gate.evidence / "harness" / f"s{gate.stage}-{args.node}-{stamp}"
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(python if python.exists() else sys.executable), "-m", "harness", "run",
           "--track", args.track, "--repo", str(gate.stage_dir.parent), "--stage", str(gate.stage),
           "--mode", args.mode, "--out", str(out)]
    proc = run(cmd, timeout=3600, cwd=kickoff, gate=gate)
    text = proc.stdout + proc.stderr
    claimed = re.search(r"claimed stage: (\S+)", text)
    claim = claimed.group(1) if claimed else "none"
    stages = dict(re.findall(r"stage (\d+): (pass|fail|error)", text))
    detail = f"claimed stage {claim}; suites {stages or 'not run'}; report {out / 'report.json'}"
    return gate.finish(proc.returncode == 0 and claim == str(gate.stage), f"exit {proc.returncode}; {detail}", claimed=claim, suites=stages,
                       report=str(out / "report.json"))


if __name__ == "__main__":
    raise SystemExit(main())
