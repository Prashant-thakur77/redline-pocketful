"""Lessons file: generic root causes the seats learn during a run.

    python -m factory.lessons add --seat builder --cause "…" --rule "…"
    python -m factory.lessons show

Seats read `plan/lessons.md` before each work item, so a mistake made once is
not made again on the next item or stage. Write the rule so it would help on
a different problem too.
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import date
from pathlib import Path

HEADER = "# Lessons\n\nGeneric root causes found during the run. Read before each work item.\n\n"


def lessons_path() -> Path:
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    root = Path(proc.stdout.strip()) if proc.returncode == 0 else Path.cwd()
    return root / "plan" / "lessons.md"


def add(path: Path, seat: str, cause: str, rule: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text() if path.exists() else HEADER
    if f"→ {rule.strip()}" in text:
        return False
    line = f"- [{seat}] {date.today().isoformat()}: {cause.strip()} → {rule.strip()}\n"
    path.write_text(text + line)
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["add", "show"])
    parser.add_argument("--seat")
    parser.add_argument("--cause")
    parser.add_argument("--rule")
    parser.add_argument("--file", type=Path)
    args = parser.parse_args(argv)
    path = args.file or lessons_path()
    if args.command == "show":
        print(path.read_text() if path.exists() else "no lessons yet")
        return 0
    if not (args.seat and args.cause and args.rule):
        parser.error("add needs --seat, --cause and --rule")
    print("added" if add(path, args.seat, args.cause, args.rule) else "already known")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
