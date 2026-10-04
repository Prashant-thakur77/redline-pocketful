"""Bring the band up: an OpenCode server (for OpenCode seats) and one supervised
process per seat, each logging to ~/.cache/redline/logs/<seat>.log.

    python -m factory.launch --repo /abs/result --kickoff /abs/task-package
    python -m factory.launch --write-opencode-config      # providers only

The OpenCode config is written to ~/.config/opencode/opencode.json, never to
the repository: keys are read from the environment (`{env:…}`) at run time.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from factory.seats import load_seats

REPO = Path(__file__).resolve().parent.parent
LOGS = Path.home() / ".cache" / "redline" / "logs"
OPENCODE_CONFIG = Path.home() / ".config" / "opencode" / "opencode.json"


def opencode_bin() -> str:
    return shutil.which("opencode") or str(Path.home() / ".opencode" / "bin" / "opencode")


def opencode_config(env: dict) -> dict:
    provider = {
        "google": {"options": {"apiKey": "{env:GEMINI_API_KEY}"}},
        "ollama": {"npm": "@ai-sdk/openai-compatible", "name": "Ollama (local)",
                   "options": {"baseURL": "http://127.0.0.1:11434/v1"},
                   "models": {"qwen2.5:7b": {}}},
    }
    if env.get("FEATHERLESS_API_KEY"):
        provider["featherless"] = {"npm": "@ai-sdk/openai-compatible", "name": "Featherless AI",
                                   "options": {"baseURL": "https://api.featherless.ai/v1",
                                               "apiKey": "{env:FEATHERLESS_API_KEY}"},
                                   "models": {"MiniMaxAI/MiniMax-M2.5": {}, "moonshotai/Kimi-K2.5": {},
                                              "deepseek-ai/DeepSeek-V3.2": {}}}
    return {"$schema": "https://opencode.ai/config.json", "provider": provider,
            "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny"}, "autoupdate": False}


def write_opencode_config(env: dict) -> Path:
    OPENCODE_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if OPENCODE_CONFIG.exists():
        OPENCODE_CONFIG.with_suffix(".json.bak").write_text(OPENCODE_CONFIG.read_text())
    OPENCODE_CONFIG.write_text(json.dumps(opencode_config(env), indent=2) + "\n")
    return OPENCODE_CONFIG


PIDS = LOGS.parent / "band.pids"
PATTERNS = ("factory.launch --repo", "factory.seat ", "opencode serve --hostname=127.0.0.1")


def band_pids_matching(pattern: str) -> list[int]:
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout
    return [int(p) for p in out.split()]


def band_pids() -> list[int]:
    pids = []
    for pattern in PATTERNS:
        out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout
        pids += [int(p) for p in out.split() if int(p) != os.getpid()]
    return pids


def stop_band(grace: float = 15.0, seats: list[str] | None = None) -> int:
    """Stop every seat (with its child processes), the OpenCode server and any launcher,
    or only the named seats."""
    global PATTERNS
    if seats:
        PATTERNS = tuple(f"factory.seat {s} " for s in seats)
    pids = band_pids()
    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError):
                pass
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and band_pids():
            time.sleep(0.5)
        pids = band_pids()
        if not pids:
            break
    PIDS.unlink(missing_ok=True)
    print("band stopped" if not band_pids() else f"still running: {band_pids()}")
    return 0 if not band_pids() else 1


def git_identity(seat) -> dict:
    """Every commit a seat makes carries the seat as author *and* committer, so git history
    never shows the human's global identity on band work."""
    email = f"{seat.key}@band.local"
    return {"GIT_AUTHOR_NAME": seat.name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": seat.name, "GIT_COMMITTER_EMAIL": email, "REDLINE_SEAT": seat.key}


def start(cmd: list[str], log: Path, env: dict) -> subprocess.Popen:
    log.parent.mkdir(parents=True, exist_ok=True)
    return subprocess.Popen(cmd, stdout=open(log, "a"), stderr=subprocess.STDOUT, env=env,
                            start_new_session=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--kickoff", type=Path)
    parser.add_argument("--seats", nargs="*", help="default: every seat in seats.yaml")
    parser.add_argument("--port", type=int, default=4096)
    parser.add_argument("--write-opencode-config", action="store_true")
    parser.add_argument("--detach", action="store_true", help="start everything and return; stop with --stop")
    parser.add_argument("--stop", action="store_true", help="stop a band started by this launcher")
    args = parser.parse_args(argv)
    if args.stop:
        return stop_band(seats=args.seats)
    load_dotenv(REPO / ".env")
    env = {**os.environ, "GOOGLE_GENERATIVE_AI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
           "OLLAMA_KEEP_ALIVE": "2m", "OLLAMA_NUM_PARALLEL": "1"}
    print(f"opencode config -> {write_opencode_config(env)}")
    if args.write_opencode_config:
        return 0
    if not args.repo or not args.repo.is_absolute():
        parser.error("--repo must be an absolute path")
    seats = load_seats()
    chosen = args.seats or list(seats)
    procs = []
    if any(seats[s].harness == "OpenCode" for s in chosen) and not band_pids_matching("opencode serve"):
        procs.append(start([opencode_bin(), "serve", "--hostname=127.0.0.1", f"--port={args.port}"],
                           LOGS / "opencode.log", env))
        time.sleep(3)
    for key in chosen:
        cmd = [sys.executable, "-m", "factory.seat", key, "--repo", str(args.repo),
               "--opencode-url", f"http://127.0.0.1:{args.port}"]
        if args.kickoff:
            cmd += ["--kickoff", str(args.kickoff)]
        procs.append(start(cmd, LOGS / f"{key}.log", {**env, "PYTHONPATH": str(REPO), **git_identity(seats[key])}))
        print(f"started {key} (log {LOGS / f'{key}.log'})")
    if args.detach:
        PIDS.write_text("\n".join(str(p.pid) for p in procs) + "\n")
        print(f"band is up (detached); stop with: make band STOP=1")
        return 0
    print("band is up; Ctrl+C stops every process")
    try:
        while any(p.poll() is None for p in procs):  # seats restart themselves; one exit never stops the band
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        for p in procs:
            if p.poll() is None:
                os.killpg(p.pid, signal.SIGTERM)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
