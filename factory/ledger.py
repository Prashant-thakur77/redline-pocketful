"""Append-only run ledger (`evidence/ledger.jsonl`) with a SHA-256 hash chain.

Each event stores the hash of the one before it, so an edited or deleted line
breaks `verify()`. Appends take a file lock: gates may run side by side.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
from pathlib import Path

from factory.events import Event

GENESIS = "0" * 64


def _parses(line: str) -> bool:
    if not line.strip():
        return True
    try:
        json.loads(line)
        return True
    except ValueError:
        return False


def digest(event: Event) -> str:
    body = event.model_dump(exclude={"hash"})
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Ledger:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def append(self, event: Event) -> Event:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.seek(0)
            lines = fh.read().splitlines(keepends=True)
            # A writer killed mid-line leaves a torn tail; drop it rather than poison every later run.
            while lines and not _parses(lines[-1]):
                lines.pop()
                fh.seek(0)
                fh.truncate()
                fh.write("".join(lines))
            last = next((ln for ln in reversed(lines) if ln.strip()), None)
            prev = json.loads(last)["hash"] if last else GENESIS
            sealed = event.model_copy(update={"prev": prev, "hash": None})
            sealed = sealed.model_copy(update={"hash": digest(sealed)})
            if lines and not lines[-1].endswith("\n"):
                fh.write("\n")
            fh.write(sealed.model_dump_json() + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return sealed

    def events(self) -> list[Event]:
        if not self.path.exists():
            return []
        lines = [ln for ln in self.path.read_text().splitlines() if ln.strip()]
        if lines and not _parses(lines[-1]):
            lines.pop()  # a torn tail is ignored; the next append removes it
        return [Event.model_validate_json(line) for line in lines]

    def verify(self) -> tuple[bool, str]:
        prev = GENESIS
        for number, event in enumerate(self.events(), 1):
            if event.prev != prev:
                return False, f"line {number}: prev does not match the line before"
            if digest(event) != event.hash:
                return False, f"line {number}: content does not match its hash"
            prev = event.hash
        return True, "ok"


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify a ledger's hash chain")
    parser.add_argument("path", nargs="?", default="evidence/ledger.jsonl")
    ok, detail = Ledger(parser.parse_args(argv).path).verify()
    print(detail)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
