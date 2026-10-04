"""The EVIDENCE block every handoff carries, as a fenced ```json block.

    ```json
    {"req": ["R-031"], "commit": "9f3c2e1", "ran": "pytest tests -q",
     "result": {"exit": 0, "passed": 148, "failed": 0},
     "log": "evidence/s1/n07-verifier.log",
     "cost": {"tokens": 41000, "usd": 0.62, "seconds": 372},
     "verdict": "GO"}
    ```
"""
from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

# READY: author hands work over. GO / NEEDS_WORK / BLOCK: verifier verdicts.
# BREACH / HOLDS: adversary found a break / found none.
Verdict = Literal["READY", "GO", "NEEDS_WORK", "BLOCK", "BREACH", "HOLDS"]
FENCE = re.compile(r"```json\s*([\s\S]*?)```")


class Result(BaseModel):
    exit: int
    passed: int = 0
    failed: int = 0


class Cost(BaseModel):
    tokens: int = 0
    usd: float = 0.0
    seconds: float = 0.0


class Evidence(BaseModel):
    req: list[str] = Field(min_length=1)
    commit: str = Field(min_length=7)
    ran: str = Field(min_length=1)
    result: Result
    log: str = Field(min_length=1)
    cost: Cost
    verdict: Verdict
    node: str | None = None
    stage: int | None = None


class EvidenceError(ValueError):
    pass


def parse_evidence(text: str) -> Evidence:
    """The first fenced json block that is a valid Evidence. Raises with every reason."""
    problems = []
    for block in FENCE.findall(text or ""):
        try:
            return Evidence.model_validate(json.loads(block))
        except (ValueError, ValidationError) as exc:
            problems.append(str(exc).splitlines()[0])
    raise EvidenceError("no valid EVIDENCE block" + (f": {'; '.join(problems)}" if problems else ""))


def try_parse(text: str) -> Evidence | None:
    try:
        return parse_evidence(text)
    except EvidenceError:
        return None


def format_handoff(text: str, evidence: Evidence, to: list[str]) -> str:
    """`@a @b text` followed by the block. Refuses an unaddressed handoff."""
    handles = [h.lstrip("@") for h in to if h]
    if not handles:
        raise EvidenceError("a handoff must address at least one seat by @handle")
    head = " ".join(f"@{h}" for h in handles)
    block = evidence.model_dump_json(indent=2, exclude_none=True)
    return f"{head} {text}\n\n```json\n{block}\n```"
