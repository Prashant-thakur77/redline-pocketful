"""Gate 5 — no regression: every earlier stage folder's tests pass against this
stage's service, and (when the hook supports it) state populated on the
previous stage's service carries over to this one unchanged."""
from __future__ import annotations

import re
from pathlib import Path

from factory.gates import hook as hooks
from factory.gates.common import Gate, Service, base_parser, failure, green, run_gate, run_pytest


def earlier_folders(stage_dir: Path, stage: int) -> list[Path]:
    found = []
    for sibling in stage_dir.parent.iterdir():
        match = re.fullmatch(rf"{re.escape(re.sub(r'\d+$', '', stage_dir.name))}(\d+)", sibling.name)
        if sibling.is_dir() and match and int(match.group(1)) < stage:
            found.append((int(match.group(1)), sibling))
    return [folder for _, folder in sorted(found)]


def upgrade(gate: Gate, previous: Path, new_url: str, args) -> str | None:
    module = hooks.load(gate.stage_dir)
    if hooks.missing(module, "populate", "snapshot", "carry"):
        gate.log("upgrade check skipped: hook has no populate/snapshot/carry")
        return None
    old = Service(previous, gate, args.health_path)
    try:
        old.build()
        old_url = old.start(args.health_timeout)
        module.populate(old_url)
        before = module.snapshot(old_url)
        module.carry(old_url, new_url)
        after = module.snapshot(new_url)
        gate.log(f"upgrade {previous.name} -> {gate.stage_dir.name}: before={before!r} after={after!r}")
        return None if before == after else f"state changed across upgrade from {previous.name}"
    finally:
        old.stop()


def check(gate: Gate, base_url: str, args) -> int:
    if gate.stage is None and not args.previous:
        return gate.finish(False, "stage unknown (folder name has no number): pass --stage or --previous")
    folders = [Path(p) for p in args.previous] if args.previous else earlier_folders(gate.stage_dir, gate.stage)
    if not folders:
        return gate.finish(True, "no earlier stage folder; nothing to regress")
    problems, ran = [], 0
    for folder in folders:
        if not (folder / "tests").is_dir():
            problems.append(f"{folder.name}/tests is missing")
            continue
        counts = run_pytest([folder / "tests"], base_url, gate)
        ran += counts["tests"]
        if not green(counts):
            problems.append(f"{folder.name} tests: {counts['failures']} failed, {counts['errors']} errors, "
                            f"{counts['skipped']} skipped of {counts['tests']}")
    try:
        broken = upgrade(gate, folders[-1], base_url, args)
    except Exception as exc:
        broken = f"upgrade check failed: {failure(exc)}"
    if broken:
        problems.append(broken)
    detail = "; ".join(problems) or f"{ran} earlier tests pass; upgrade from {folders[-1].name} ok"
    return gate.finish(not problems, detail, earlier=[f.name for f in folders])


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--previous", nargs="*", help="earlier stage folders (default: siblings)")
    args = parser.parse_args(argv)
    gate = Gate("g5", args)
    return run_gate(gate, args, lambda url: check(gate, url, args))


if __name__ == "__main__":
    raise SystemExit(main())
