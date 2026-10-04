"""Does a file name the problem instead of the factory?

Three sources of banned terms, none stored in this package:
  - the kickoff harness vocabulary (every track's endpoints, fields, error codes)
  - a plain word list (product nouns), one per line, e.g. plan/track-words.txt
  - stage numbers used as requirements ("stage N" with a digit)
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

STAGE_REF = re.compile(r"\bstages?[\s_-]*[1-4]\b", re.I)
SHAPES = (
    re.compile(r"(?<![a-z0-9_])/[a-z][a-z0-9_]*(?:[/-][a-z0-9_{}]+)*"),
    re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b"),
    re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b"),
)


def kickoff_vocabulary(kickoff: Path | str | None) -> set[str]:
    if not kickoff:
        return set()
    path = Path(kickoff) / "harness" / "vocabulary.py"
    if not path.is_file():
        raise FileNotFoundError(f"{path} not found; pass the kickoff checkout")
    spec = importlib.util.spec_from_file_location("kickoff_vocabulary", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return {term for terms in module.TRACK_VOCABULARY.values() for term in terms}


def word_list(path: Path | str | None) -> set[str]:
    if not path or not Path(path).is_file():
        return set()
    return {w.strip().lower() for w in Path(path).read_text().splitlines()
            if w.strip() and not w.startswith("#")}


def scan_text(text: str, vocabulary: set[str], words: set[str]) -> list[tuple[int, str]]:
    hits = []
    # `<table>` markup and a `table{` CSS rule are HTML, not a product noun.
    word_re = (re.compile(r"(?<![</])\b(" + "|".join(map(re.escape, sorted(words))) + r")s?\b(?![>{])", re.I)
               if words else None)
    for number, line in enumerate(text.splitlines(), 1):
        lowered = line.lower()
        for shape in SHAPES:
            hits += [(number, t) for t in shape.findall(lowered) if t in vocabulary]
        if word_re:
            hits += [(number, m.group(0).lower()) for m in word_re.finditer(line)]
        hits += [(number, m.group(0).lower()) for m in STAGE_REF.finditer(line)]
    return hits


def prose_of_python(source: str) -> str:
    """Only comments and string literals, kept on their original lines: that is
    where track detail would leak. Standard-library identifiers are not prose."""
    import io
    import tokenize

    lines = [""] * (source.count("\n") + 2)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING) or tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
                for offset, part in enumerate(tok.string.splitlines() or [""]):
                    lines[tok.start[0] - 1 + offset] += " " + part
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source
    return "\n".join(lines)


def scan(paths: list[Path], vocabulary: set[str], words: set[str]) -> list[str]:
    problems = []
    for path in paths:
        text = path.read_text(errors="replace")
        if path.suffix == ".py":
            text = prose_of_python(text)
        for number, term in scan_text(text, vocabulary, words):
            problems.append(f"{path}:{number}: `{term}`")
    return problems


def files_under(*roots: Path | str, suffixes=(".md", ".py", ".yaml", ".yml", ".txt", ".sh")) -> list[Path]:
    out = []
    for root in roots:
        root = Path(root)
        if root.is_file():
            out.append(root)
        elif root.is_dir():
            out += [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in suffixes
                    and "__pycache__" not in p.parts]
    return out


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Fail if any file names track detail")
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--kickoff", help="kickoff checkout (for the harness vocabulary)")
    parser.add_argument("--words", default="plan/track-words.txt")
    parser.add_argument("--exclude", action="append", default=[],
                        help="path prefix to skip (e.g. the word list itself)")
    args = parser.parse_args(argv)
    files = [p for p in files_under(*args.paths)
             if not any(str(p).startswith(x) for x in args.exclude)]
    problems = scan(files, kickoff_vocabulary(args.kickoff), word_list(args.words))
    for p in problems:
        print(p)
    print(f"{len(problems)} hit(s) in {len(files)} file(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
