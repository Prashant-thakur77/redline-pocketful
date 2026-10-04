"""Run a set of gates on one stage folder, sharing one offline service.

    python -m factory.gates.run stage-<N> --node <id> --gates 1,2,4,8
    python -m factory.gates.run stage-<N> --node close --gates all --scope <base>..HEAD \
        [--track <name> --kickoff <path>]

Gate 1 runs first; if the folder does not build and start, the gates that need
a service are reported as failed without running. Exit 0 only if all pass.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from factory import scope
from factory.gates import (g1_clean_build, g2_spec_tests, g3_public_checks, g4_storm, g5_regression,
                           g6_mutation, g7_ui, g8_budget)
from factory.gates import hook as hooks
from factory.gates.common import Gate, Service, failure, head_commit, prune_images, repo_root, stage_number
from factory.ledger import Ledger

# Gates sharing one service, in this order: the storm goes last because it leaves the
# most state behind. Gate 5 gets its own fresh service (earlier stages' tests may assume one).
SHARED_ORDER = ("2", "7", "4")
MODULES = {"1": g1_clean_build, "2": g2_spec_tests, "3": g3_public_checks, "4": g4_storm,
           "5": g5_regression, "6": g6_mutation, "7": g7_ui, "8": g8_budget}


def parse_gates(text: str, args, stage_dir: Path) -> list[str]:
    if text != "all":
        return [g.strip().lstrip("g") for g in text.split(",") if g.strip()]
    gates = ["1", "2", "4", "5", "6", "8"]
    if args.track and args.kickoff:
        gates.insert(2, "3")
    module = hooks.load(stage_dir)
    if args.routes or getattr(module, "UI_ROUTES", None):
        gates.insert(-1, "7")
    return gates


def scope_gate(args, stage: int | None, evidence: Path) -> bool:
    ns = argparse.Namespace(stage_dir=args.stage_dir, stage=stage, node=args.node, evidence=evidence)
    gate = Gate("scope", ns)
    try:
        found = scope.violations(repo_root(args.stage_dir), args.scope)
    except Exception as exc:  # bad range, not a repo
        return gate.finish(False, f"scope check could not run: {exc}") == 0
    gate.log(*(found or ["every commit inside its seat's scope"]))
    return gate.finish(not found, "; ".join(found[:5]) or f"{args.scope}: all commits in scope",
                       violations=found) == 0


def guarded(name: str, call) -> bool:
    """One gate's crash fails that gate and never stops the others."""
    try:
        return call() == 0
    except Exception as exc:  # the gate wrote no event; say why here
        print(f"{name}: FAIL — crashed: {failure(exc)}")
        return False


def checkout(root: Path, commit: str) -> Path:
    """A private worktree at `commit`: never touch the shared working tree other seats use."""
    target = Path(tempfile.mkdtemp(prefix="redline-wt-"))
    subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", "--force", str(target), commit],
                   check=True, capture_output=True, text=True)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage_dir", type=Path)
    parser.add_argument("--gates", default="1,2,4,8")
    parser.add_argument("--commit", help="check this commit in a private worktree (default: the working tree)")
    parser.add_argument("--stage", type=int)
    parser.add_argument("--node", default="adhoc")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--scope", help="commit range for the edit-boundary check")
    parser.add_argument("--track")
    parser.add_argument("--kickoff", type=Path)
    parser.add_argument("--routes", nargs="*")
    parser.add_argument("--mutants", type=int, default=10)
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--json-out", type=Path, help="also write the summary here")
    args = parser.parse_args(argv)

    root = repo_root(args.stage_dir.resolve())
    evidence = (args.evidence or root / "evidence").resolve()
    worktree = checkout(root, args.commit) if args.commit else None
    try:
        stage_dir = (worktree / args.stage_dir.resolve().relative_to(root)) if worktree else args.stage_dir.resolve()
        return run_gates(args, stage_dir, evidence)
    finally:
        if worktree:
            subprocess.run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)],
                           capture_output=True)
        prune_images()


def run_gates(args, stage_dir: Path, evidence: Path) -> int:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    stage = args.stage if args.stage is not None else stage_number(stage_dir)
    common = [str(stage_dir), "--node", args.node, "--evidence", str(evidence), "--health-path", args.health_path]
    if stage is not None:
        common += ["--stage", str(stage)]
    gates = parse_gates(args.gates, args, stage_dir)
    results: dict[str, bool] = {}

    if args.scope:
        results["scope"] = guarded("scope", lambda: 0 if scope_gate(args, stage, evidence) else 1)
    if "1" in gates:
        results["g1"] = guarded("g1", lambda: g1_clean_build.main(common))
    shared = [g for g in SHARED_ORDER if g in gates]
    if shared and results.get("g1", True):
        service = Service(stage_dir, None, args.health_path)
        try:
            service.build()
            url = service.start()
            for g in shared:
                extra = ["--routes", *args.routes] if g == "7" and args.routes else []
                results[f"g{g}"] = guarded(f"g{g}", lambda g=g, extra=extra: MODULES[g].main([*common, "--base-url", url, *extra]))
        except Exception as exc:
            for g in shared:
                results.setdefault(f"g{g}", False)
            print(f"service would not start: {failure(exc)}")
        finally:
            service.stop()
    elif shared:
        for g in shared:
            results[f"g{g}"] = False
    for g in gates:
        if g == "3" and not (args.track and args.kickoff):
            print("g3: FAIL — needs --track and --kickoff")
            results["g3"] = False
        elif g in ("3", "5", "6", "8"):
            if g == "5" and not results.get("g1", True):
                results["g5"] = False
                continue
            extra = {"3": ["--track", str(args.track), "--kickoff", str(args.kickoff)],
                     "6": ["--mutants", str(args.mutants)]}.get(g, [])
            results[f"g{g}"] = guarded(f"g{g}", lambda g=g, extra=extra: MODULES[g].main([*common, *extra]))

    this_run = [e for e in Ledger(evidence / "ledger.jsonl").events()
                if e.kind == "gate_result" and e.node == args.node and e.ts >= started]
    latest = {e.payload["gate"]: e for e in this_run}
    summary = {"commit": head_commit(stage_dir), "stage": stage, "node": args.node,
               "gates": {g: ("pass" if ok else "fail") for g, ok in results.items()},
               "logs": {g: e.payload.get("log") for g, e in latest.items() if g in results}}
    counts = latest["g2"].payload.get("counts", {}) if "g2" in latest else {}
    summary["result"] = {"exit": 0 if results and all(results.values()) else 1,
                         "passed": counts.get("passed", 0), "failed": counts.get("failures", 0)}
    print(json.dumps(summary, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2))
    return 0 if results and all(results.values()) else 1

if __name__ == "__main__":
    raise SystemExit(main())
