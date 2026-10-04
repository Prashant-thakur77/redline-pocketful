"""Create a fresh result repository for a run: the factory, the mandates and
the docs, committed once by the human and tagged `factory-seed`. Everything
after that tag is the band's work, and the scope check starts there.

    python -m factory.seed_result_repo /abs/path/to/result [--venv]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COPY = ["factory", "mandates", "pyproject.toml", "README.md", "FACTORY.md"]
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", "*.egg-info")
GITIGNORE = """__pycache__/
*.pyc
.venv/
node_modules/
.pytest_cache/
*.egg-info/
.env
"""
LESSONS = "# Lessons\n\nGeneric root causes found during the run. Read before each work item.\n\n"


def git(target: Path, *args: str, author: str | None = None):
    who = ["-c", f"user.name={author}", "-c", "user.email=human@band.local"] if author else []
    subprocess.run(["git", "-C", str(target), *who, *args], check=True, capture_output=True, text=True)


def seed(target: Path, author: str) -> str:
    if not target.is_absolute():
        raise ValueError("give an absolute path: seats must all see the same repository")
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"{target} is not empty; every run gets a fresh repository")
    target.mkdir(parents=True, exist_ok=True)
    for name in COPY:
        source = REPO / name
        if source.is_dir():
            shutil.copytree(source, target / name, ignore=IGNORE)
        elif source.is_file():
            shutil.copy2(source, target / name)
    (target / ".gitignore").write_text(GITIGNORE)
    from factory.seat import claude_settings
    (target / ".claude").mkdir(exist_ok=True)
    (target / ".claude" / "settings.json").write_text(json.dumps(claude_settings(target), indent=2) + "\n")
    (target / "plan").mkdir(exist_ok=True)
    (target / "plan" / "lessons.md").write_text(LESSONS)
    (target / "evidence").mkdir(exist_ok=True)
    (target / "evidence" / ".gitkeep").write_text("")
    git(target, "init", "-q", "-b", "main")
    git(target, "add", ".")
    git(target, "commit", "-qm", "Seed factory, mandates and docs", author=author)
    git(target, "tag", "factory-seed")
    return subprocess.run(["git", "-C", str(target), "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


def make_venv(target: Path):
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", "-q", "--python", "3.12", str(target / ".venv")], check=True)
        subprocess.run([uv, "pip", "install", "-q", "--python", str(target / ".venv" / "bin" / "python"),
                        "-e", f"{target}[dev,ui,band]"], check=True)
    else:
        subprocess.run([sys.executable, "-m", "venv", str(target / ".venv")], check=True)
        subprocess.run([str(target / ".venv" / "bin" / "pip"), "install", "-q", "-e", f"{target}[dev,ui,band]"],
                       check=True)
    subprocess.run([str(target / ".venv" / "bin" / "python"), "-m", "playwright", "install", "chromium"],
                   check=True, capture_output=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", type=Path)
    parser.add_argument("--author", default="Human")
    parser.add_argument("--venv", action="store_true", help="also create .venv with the factory installed")
    args = parser.parse_args(argv)
    try:
        commit = seed(args.target, args.author)
    except (ValueError, FileExistsError) as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.venv:
        make_venv(args.target)
    print(f"seeded {args.target} at {commit} (tag factory-seed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
