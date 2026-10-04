"""Preflight: everything the dark run needs, checked in seconds before dispatch.

Adapted from Freight Room's preflight. Checks: distinct seat identities on one
BAND account, mandate headers match the roster, mandates are track-free, model
keys (optionally probed), Docker, the kickoff harness, and an offline build.

Read-only. Never prints a key. Exit 0 only when nothing FAILs and nothing is
TODO (use --allow-todo while human setup items are still open).
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from factory import genericity
from factory.band import registry
from factory.seats import load_seats

OK, TODO, FAIL = "OK", "TODO", "FAIL"
REPO = Path(__file__).resolve().parent.parent


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, status: str, label: str, detail: str = ""):
        self.rows.append((status, label, detail))
        print(f"[{status:^4}] {label}" + (f" — {detail}" if detail else ""))

    def code(self, allow_todo: bool) -> int:
        statuses = {s for s, _, _ in self.rows}
        return 1 if FAIL in statuses or (TODO in statuses and not allow_todo) else 0


def check_seats(report: Report, env: dict, transport=None, minimum: int = 5):
    seats = load_seats()
    ids, owners = {}, set()
    for key in seats:
        try:
            ident = registry.resolve(key, env, transport=transport)
        except registry.MissingSeat as exc:
            status = TODO if "set BAND_" in str(exc) else FAIL
            report.add(status, f"seat {key}", str(exc))
            continue
        except Exception as exc:  # network, DNS
            report.add(FAIL, f"seat {key}", f"BAND unreachable: {str(exc)[:120]}")
            continue
        if ident.id in ids:
            report.add(FAIL, f"seat {key}", f"same identity as {ids[ident.id]}; register a distinct agent")
            continue
        ids[ident.id] = key
        owners.add(ident.owner)
        report.add(OK, f"seat {key}", f"{ident.handle} ({ident.id[:8]}…)")
    if ids and len(owners) > 1:
        report.add(FAIL, "one BAND account", f"seats span {len(owners)} accounts; cross-account joins wait for consent")
    if len(ids) >= minimum:
        report.add(OK, "distinct seats", f"{len(ids)} ≥ {minimum}")


HEADER = re.compile(r"^(Harness|Model):\s*(\S.*)$")


def check_mandates(report: Report, mandates: Path, kickoff: Path | None, words: Path):
    seats = load_seats()
    for key, seat in seats.items():
        path = mandates / f"{key}.md"
        if not path.is_file():
            report.add(FAIL, f"mandate {key}", f"{path} missing")
            continue
        lines = [ln.strip() for ln in path.read_text().splitlines() if ln.strip()][:2]
        found = dict(m.groups() for m in map(HEADER.match, lines) if m)
        want = {"Harness": seat.harness, "Model": seat.model}
        if found != want:
            report.add(FAIL, f"mandate {key}", f"first lines must be {want}, found {found}")
        else:
            report.add(OK, f"mandate {key}", f"{seat.harness} / {seat.model}")
    vocab = genericity.kickoff_vocabulary(kickoff) if kickoff else set()
    hits = genericity.scan(genericity.files_under(mandates), vocab, genericity.word_list(words))
    if not kickoff:
        report.add(TODO, "mandate genericity", "pass --kickoff to include the harness vocabulary")
    report.add(FAIL if hits else OK, "mandates track-free", "; ".join(hits[:5]) or "0 hits")


def _run(cmd: list[str], timeout: int = 120, cwd=None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)


def probe_google(model: str, key: str) -> tuple[bool, str]:
    import time

    import httpx
    status = 0
    for attempt in range(4):  # 429/503 are routine on free tiers: back off before calling it a failure
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                       params={"key": key}, timeout=60,
                       json={"contents": [{"parts": [{"text": "Reply with: ok"}]}]})
        status = r.status_code
        if status not in (429, 500, 503):
            break
        time.sleep(5 * 2 ** attempt)
    return status == 200, f"HTTP {status}"


def check_models(report: Report, env: dict, probe: bool, run=_run):
    seats = load_seats()
    harnesses = {s.harness for s in seats.values()}
    if "Claude Code" in harnesses:
        cli = shutil.which("claude")
        report.add(OK if cli else TODO, "Claude Code CLI",
                   "logged-in CLI drives the Claude seats" if cli else "install Claude Code, run `claude` then /login")
    if "Codex" in harnesses:
        codex = shutil.which("codex")
        logged_in = (Path.home() / ".codex" / "auth.json").exists()
        report.add(OK if codex and logged_in else TODO, "Codex CLI",
                   "logged-in CLI drives the Codex seats" if codex and logged_in else "install Codex, run `codex login`")
    if "OpenCode" in harnesses:
        oc = shutil.which("opencode") or (Path.home() / ".opencode" / "bin" / "opencode")
        report.add(OK if Path(oc).exists() else FAIL, "OpenCode CLI", str(oc))
    providers = {s.provider for s in seats.values() if s.harness == "OpenCode"}
    if "google" in providers:
        report.add(OK if env.get("GEMINI_API_KEY") else TODO, "Gemini key",
                   "" if env.get("GEMINI_API_KEY") else "set GEMINI_API_KEY in .env")
    if any(f.startswith("ollama:") for s in seats.values() for f in s.fallbacks):
        report.add(OK if shutil.which("ollama") else TODO, "Ollama (local fallback)",
                   "fallback only; never runs during builds" if shutil.which("ollama") else "install ollama")
    if env.get("FEATHERLESS_API_KEY"):
        report.add(OK, "Featherless key", "present (optional)")
    if not probe:
        return
    for key, seat in seats.items():
        if seat.harness == "Claude Code" and shutil.which("claude"):
            proc = run(["claude", "-p", "Reply with: ok", "--model", seat.model, "--output-format", "text"])
            report.add(OK if proc.returncode == 0 else FAIL, f"probe {key}", seat.model)
        elif seat.harness == "Codex" and shutil.which("codex"):
            proc = run(["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only", "-m", seat.model,
                        "Reply with: ok"], 180)
            report.add(OK if proc.returncode == 0 else FAIL, f"probe {key}", seat.model)
        elif seat.provider == "google" and env.get("GEMINI_API_KEY"):
            ok, detail = probe_google(seat.model, env["GEMINI_API_KEY"])
            report.add(OK if ok else FAIL, f"probe {key}", f"{seat.model} {detail}")


def check_tools(report: Report, kickoff: Path | None, run=_run):
    docker = run(["docker", "info", "--format", "{{.ServerVersion}}"], 30) if shutil.which("docker") else None
    report.add(OK if docker and docker.returncode == 0 else FAIL, "Docker daemon",
               docker.stdout.strip() if docker and docker.returncode == 0 else "not running")
    if kickoff:
        py = kickoff / ".venv" / "bin" / "python"
        proc = run([str(py if py.exists() else sys.executable), "-m", "harness", "--help"], 60, cwd=kickoff)
        report.add(OK if proc.returncode == 0 else FAIL, "kickoff harness", str(kickoff))


def check_offline_build(report: Report, build_dir: Path):
    from factory.gates import g1_clean_build
    code = g1_clean_build.main([str(build_dir), "--evidence", str(REPO / "evidence" / "preflight")])
    report.add(OK if code == 0 else FAIL, "offline build", str(build_dir))


def write_readiness(report: Report, path: Path, code: int):
    from datetime import datetime, timezone
    mark = {OK: "✅", TODO: "⏳", FAIL: "❌"}
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# Readiness — verified live {stamp}", "",
             f"Result: **{'GREEN' if code == 0 else 'NOT READY'}** (`make preflight`)", "",
             "| Check | Status | Detail |", "|---|---|---|"]
    lines += [f"| {label} | {mark[status]} | {detail.replace('|', '/')} |" for status, label, detail in report.rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Redline preflight")
    parser.add_argument("--kickoff", type=Path, help="dark-factory-wearedevs checkout")
    parser.add_argument("--mandates", type=Path, default=REPO / "mandates")
    parser.add_argument("--words", type=Path, default=REPO / "plan" / "track-words.txt")
    parser.add_argument("--probe-models", action="store_true")
    parser.add_argument("--build-dir", type=Path, help="a service folder to build and start offline")
    parser.add_argument("--allow-todo", action="store_true", help="exit 0 with human TODO items open")
    parser.add_argument("--write", type=Path, help="also write a dated readiness record (markdown) here")
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env")
    env = dict(os.environ)
    report = Report()
    check_seats(report, env)
    check_mandates(report, args.mandates, args.kickoff, args.words)
    check_models(report, env, args.probe_models)
    check_tools(report, args.kickoff)
    if args.build_dir:
        check_offline_build(report, args.build_dir)
    code = report.code(args.allow_todo)
    if args.write:
        write_readiness(report, args.write, code)
    todo = sum(1 for s, _, _ in report.rows if s == TODO)
    print(("GREEN" if code == 0 else "NOT READY") + (f" ({todo} human TODO item(s))" if todo else ""))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
