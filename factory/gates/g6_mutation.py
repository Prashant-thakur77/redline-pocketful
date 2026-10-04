"""Gate 6 — mutation bite: break the code on purpose (flip comparisons and
arithmetic, swap booleans, change rounding, drop locks) and check the tests
notice. At least 80% of the mutants that still start must be killed.

Language-agnostic: mutants are regex rewrites of source lines, applied to a
temporary copy, rebuilt with the folder's own Dockerfile and tested over HTTP.
"""
from __future__ import annotations

import random
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from factory.gates.common import Gate, Service, base_parser, failure, green, run, run_pytest

SOURCE_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs"}
SKIP_PARTS = {"tests", "test", "node_modules", "dist", "build", "vendor", "static", "public",
              "assets", ".git", "__pycache__", "migrations"}
COMMENT = re.compile(r"^\s*(#|//|\*|/\*)")

# (name, pattern, replacement, suffixes or None for all)
OPERATORS = [
    ("cmp <= to <", r" <= ", " < ", None),
    ("cmp >= to >", r" >= ", " > ", None),
    ("cmp < to <=", r" < ", " <= ", None),
    ("cmp > to >=", r" > ", " >= ", None),
    ("eq to ne", r" === ", " !== ", None),
    ("ne to eq", r" !== ", " === ", None),
    ("eq to ne", r" == ", " != ", None),
    ("ne to eq", r" != ", " == ", None),
    ("plus to minus", r" \+ ", " - ", None),
    ("minus to plus", r" - ", " + ", None),
    ("add-assign to sub", r" \+= ", " -= ", None),
    ("sub-assign to add", r" -= ", " += ", None),
    ("and to or", r" and ", " or ", {".py"}),
    ("or to and", r" or ", " and ", {".py"}),
    ("&& to ||", r" && ", " || ", None),
    ("|| to &&", r" \|\| ", " && ", None),
    ("true to false", r"\bTrue\b", "False", {".py"}),
    ("true to false", r"\btrue\b", "false", None),
    ("floor-div to div", r" // ", " / ", {".py"}),
    ("round to trunc", r"\bround\(", "int(", {".py"}),
    ("floor to ceil", r"Math\.floor\(", "Math.ceil(", None),
    ("round to floor", r"Math\.round\(", "Math.floor(", None),
    ("drop lock", r"^(\s*)(async\s+)?with\s+[^:]*[Ll]ock[^:]*:", r"\1if True:", {".py"}),
    ("drop lock", r"await\s+[\w.]*(?:lock|mutex)[\w.]*\.(?:acquire|lock|runExclusive)\(\)", "undefined", None),
    ("weaker tx", r"BEGIN IMMEDIATE", "BEGIN DEFERRED", None),
    ("drop row lock", r"\s+FOR UPDATE", "", None),
]


@dataclass
class Mutant:
    file: Path
    line: int
    name: str
    before: str
    after: str


def inside_string(line: str, col: int) -> bool:
    head = line[:col]
    return head.count('"') % 2 == 1 or head.count("'") % 2 == 1 or head.count("`") % 2 == 1


def sources(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in SOURCE_SUFFIXES
            and not (SKIP_PARTS & set(p.relative_to(root).parts)) and not p.name.endswith(".min.js")]


def non_code_spans(path: Path, text: str) -> dict[int, list[tuple[int, int]]]:
    """Per line, the column spans that are comments or string literals (docstrings included).
    Mutating those changes no behaviour, so they are never mutated."""
    spans: dict[int, list[tuple[int, int]]] = {}
    if path.suffix == ".py":
        import io
        import tokenize
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type in (tokenize.COMMENT, tokenize.STRING) or tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
                    (r1, c1), (r2, c2) = tok.start, tok.end
                    for row in range(r1, r2 + 1):
                        spans.setdefault(row, []).append((c1 if row == r1 else 0, c2 if row == r2 else 10**6))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            pass
        return spans
    for number, line in enumerate(text.splitlines(), 1):
        cut = next((m.start() for m in re.finditer(r"//", line) if not inside_string(line, m.start())), None)
        if cut is not None:
            spans.setdefault(number, []).append((cut, 10**6))
    return spans


def candidates(root: Path) -> list[Mutant]:
    found = []
    for path in sources(root):
        text = path.read_text(errors="replace")
        skip = non_code_spans(path, text)
        for number, line in enumerate(text.splitlines(), 1):
            if COMMENT.match(line) or len(line) > 300:
                continue
            for name, pattern, repl, suffixes in OPERATORS:
                if suffixes and path.suffix not in suffixes:
                    continue
                for match in re.finditer(pattern, line):
                    if inside_string(line, match.start()) or any(
                            a <= match.start() < b for a, b in skip.get(number, ())):
                        continue
                    after = line[:match.start()] + match.expand(repl) + line[match.end():]
                    found.append(Mutant(path.relative_to(root), number, name, line, after))
    return found


def apply(root: Path, mutant: Mutant) -> str:
    path = root / mutant.file
    original = path.read_text(errors="replace")
    lines = original.splitlines(keepends=True)
    ending = "\n" if lines[mutant.line - 1].endswith("\n") else ""
    lines[mutant.line - 1] = mutant.after + ending
    path.write_text("".join(lines))
    return original


def tested(work: Path, gate: Gate, args, tag: str, extra=("-x",)) -> bool | None:
    """True if the suite passes on `work`, False if it fails, None if the service never starts."""
    service = Service(work, gate, args.health_path, tag=tag)
    try:
        service.build()
        url = service.start(args.health_timeout)
    except Exception:
        service.stop()
        return None
    try:
        return green(run_pytest([work / "tests"], url, gate, timeout=args.mutant_timeout, extra=list(extra)))
    finally:
        service.stop()
        run(["docker", "rmi", "-f", tag], 120)


def check(gate: Gate, args) -> int:
    if not (gate.stage_dir / "tests").is_dir():
        return gate.finish(False, "tests/ is missing; nothing can kill a mutant")
    pool = candidates(gate.stage_dir)
    if not pool:
        return gate.finish(False, "no mutable source lines found")
    rng = random.Random(args.seed)
    rng.shuffle(pool)
    picked = pool[:args.mutants]
    killed, survived, stillborn = [], [], []
    run_id = uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix="redline-mut-") as tmp:
        work = Path(tmp) / gate.stage_dir.name
        shutil.copytree(gate.stage_dir, work, ignore=shutil.ignore_patterns(".git", "node_modules"))
        baseline = tested(work, gate, args, f"redline-mut-{run_id}-base", extra=())
        if baseline is not True:
            return gate.finish(False, "baseline not green: the unmutated code must pass its own tests "
                                     "before mutants can be judged")
        for index, mutant in enumerate(picked, 1):
            label = f"#{index} {mutant.file}:{mutant.line} [{mutant.name}]"
            original = apply(work, mutant)
            try:
                outcome = tested(work, gate, args, f"redline-mut-{run_id}-{index}")
            finally:
                (work / mutant.file).write_text(original)
            if outcome is None:
                stillborn.append(label)
                gate.log(f"{label}: stillborn (does not build or start)")
                continue
            (survived if outcome else killed).append(label)
            gate.log(f"{label}: {'SURVIVED' if outcome else 'killed'}",
                     f"   - {mutant.before.strip()}", f"   + {mutant.after.strip()}")
    valid = len(killed) + len(survived)
    score = len(killed) / valid if valid else 0.0
    detail = (f"killed {len(killed)}/{valid} valid mutants ({score:.0%}, need {args.threshold:.0%}); "
              f"{len(stillborn)} stillborn; {len(pool)} candidates")
    if survived:
        detail += f"; survivors: {', '.join(survived[:3])}"
    passed = valid >= args.min_valid and score >= args.threshold
    return gate.finish(passed, detail, score=round(score, 3), killed=len(killed),
                       survived=survived, stillborn=len(stillborn), candidates=len(pool))


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--mutants", type=int, default=10, help="how many to sample")
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--min-valid", type=int, default=5)
    parser.add_argument("--mutant-timeout", type=float, default=180)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args(argv)
    gate = Gate("g6", args)
    try:
        return check(gate, args)
    except Exception as exc:
        return gate.finish(False, failure(exc))


if __name__ == "__main__":
    raise SystemExit(main())
