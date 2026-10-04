"""Seat roster: which harness and model each seat runs, and what it may edit.

Loaded from `seats.yaml`, the single source of truth that preflight checks
against the mandate headers.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

from factory import ROOT

DEFAULT_PATH = ROOT / "seats.yaml"


def glob_match(path: str, pattern: str) -> bool:
    """`*` stays inside one path segment; `**` crosses segments (`a/**` matches everything under a/)."""
    regex = ""
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            regex += ".*"
            i += 2
        elif pattern[i] == "*":
            regex += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            regex += "[^/]"
            i += 1
        else:
            regex += re.escape(pattern[i])
            i += 1
    return re.fullmatch(regex, path) is not None


class Seat(BaseModel):
    key: str
    name: str
    harness: str
    model: str
    edits: list[str] = []
    forbid: list[str] = []
    also: list[str] = []
    fallbacks: list[str] = []
    effort: str | None = None  # Claude seats: low | medium | high | max (default high)
    provider: str | None = None

    def may_edit(self, path: str) -> bool:
        if any(glob_match(path, pattern) for pattern in self.also):
            return True
        if any(glob_match(path, pattern) for pattern in self.forbid):
            return False
        return any(glob_match(path, pattern) for pattern in self.edits)


def load_seats(path: Path | str = DEFAULT_PATH) -> dict[str, Seat]:
    raw = yaml.safe_load(Path(path).read_text())
    seats = raw.get("seats") if isinstance(raw, dict) else None
    if not isinstance(seats, dict) or not seats:
        raise ValueError(f"{path}: expected a non-empty `seats:` mapping")
    return {key: Seat(key=key, **body) for key, body in seats.items()}


def model_for(seat: str, path: Path | str = DEFAULT_PATH) -> str:
    seats = load_seats(path)
    if seat not in seats:
        raise KeyError(f"unknown seat {seat!r}; known: {sorted(seats)}")
    return seats[seat].model
