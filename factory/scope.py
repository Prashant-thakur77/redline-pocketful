"""Edit-boundary check over a commit range: every commit's author must be a
seat, and every path it touched must be inside that seat's scope.

A commit whose committer is not its author (one seat, or the human, committing
under another seat's name) is reported. Allowed for every seat: `evidence/**` (gate output) and `plan/lessons.md`.
A file added under a stage folder with the same content as the previous stage
folder's copy is a copy-forward, not authorship. Deleting a test is always
reported: the verifier decides whether it is a BLOCK. A path that is back to
its original content at the end of the range was reverted by its owner and no
longer counts; the attempt stays in history and in the verdict ledger.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

from factory.seats import Seat, glob_match, load_seats

SHARED = ["evidence/**", "plan/lessons.md"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def blob(repo: Path, commit: str, path: str) -> str | None:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", f"{commit}:{path}"], capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else None


def copied_forward(repo: Path, commit: str, path: str) -> bool:
    match = re.match(r"^([^/]*?)(\d+)/(.+)$", path)
    if not match or int(match.group(2)) < 2:
        return False
    source = f"{match.group(1)}{int(match.group(2)) - 1}/{match.group(3)}"
    return blob(repo, commit, path) is not None and blob(repo, commit, path) == blob(repo, commit, source)


def seat_of(author: str, seats: dict[str, Seat]) -> Seat | None:
    key = author.strip().lower()
    return next((s for s in seats.values() if key in (s.key, s.name.lower())), None)


def restored(repo: Path, commit: str, span: str, path: str) -> bool:
    """The path is back, at the end of the range, to what it was before `commit`."""
    before = blob(repo, f"{commit}^", path)
    end = span.split("..", 1)[1].lstrip(".") if ".." in span else "HEAD"
    return before is not None and before == blob(repo, end or "HEAD", path)


def violations(repo: Path, span: str, seats: dict[str, Seat] | None = None) -> list[str]:
    seats = seats or load_seats()
    found = []
    for line in git(repo, "log", "--format=%H%x09%an%x09%cn", span).splitlines():
        commit, author, committer = line.split("\t", 2)
        seat = seat_of(author, seats)
        short = commit[:10]
        if seat is None:
            fields = git(repo, "show", "--format=", "--name-only", "-z", commit).split("\0")
            paths = [f for f in fields if f]
            if paths and all(glob_match(f, "factory/**") for f in paths):
                continue  # factory maintenance: the tools, never the band's output (stated in FACTORY.md)
            found.append(f"{short}: author {author!r} is not a seat")
            continue
        if committer.strip().lower() != author.strip().lower():
            found.append(f"{short}: committed by {committer!r} under {author!r}'s name")
            continue
        fields = git(repo, "show", "--format=", "--name-status", "--no-renames", "-z", commit).split("\0")
        for status, path in zip(fields[0::2], fields[1::2]):
            if not status:
                continue
            if restored(repo, commit, span, path):
                continue
            if status.startswith("D") and re.search(r"(^|/)tests/", path):
                found.append(f"{short}: {seat.key} deleted test {path}")
                continue
            if seat.may_edit(path) or any(glob_match(path, p) for p in SHARED):
                continue
            if status.startswith("A") and copied_forward(repo, commit, path):
                continue
            found.append(f"{short}: {seat.key} edited {path} outside its scope")
    return found


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("span", help="commit range, e.g. abc123..HEAD")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    found = violations(args.repo, args.span)
    print("\n".join(found) or "every commit is inside its seat's scope")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
