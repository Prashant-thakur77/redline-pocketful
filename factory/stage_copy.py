"""Copy a finished stage folder forward to start the next one.

    python -m factory.stage_copy stage-<N> stage-<N+1>

Refuses to overwrite, and never carries a nested `.git` (a folder that is its
own repository arrives empty in a clone), build output or caches.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

IGNORE = shutil.ignore_patterns(".git", "node_modules", "__pycache__", ".pytest_cache", "dist",
                                ".venv", "*.pyc", "evidence")


def copy_forward(source: Path, target: Path) -> int:
    if not source.is_dir():
        raise FileNotFoundError(f"{source} does not exist")
    if target.exists():
        raise FileExistsError(f"{target} already exists; a stage is copied forward once")
    shutil.copytree(source, target, ignore=IGNORE)
    return sum(1 for p in target.rglob("*") if p.is_file())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    args = parser.parse_args(argv)
    try:
        count = copy_forward(args.source, args.target)
    except (FileNotFoundError, FileExistsError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"copied {count} files {args.source} -> {args.target}; commit them alone, then extend the copy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
