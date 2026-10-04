"""Run one seat as a BAND SDK agent, with its mandate as standing instructions.

    python -m factory.seat <seat> --repo /abs/result [--kickoff /abs/task-package]

- Claude Code seats run the Claude Agent SDK (the local `claude` login, no API
  key needed) in `dontAsk` mode with the repo's `.claude/settings.json`
  allowlist: nothing ever prompts a human, and anything off the list is denied.
- Codex seats run `codex app-server` on the local ChatGPT login with approvals
  off and a workspace-write sandbox (repo and tool caches writable).
- OpenCode seats talk to a local `opencode serve`; tool calls are auto-accepted
  and questions meant for a human are auto-rejected.

A supervisor restarts the seat when it dies. On a rate or usage limit it waits
with exponential backoff and moves to the next model in the seat's fallback
list, so a limit pauses the work instead of stopping it.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from factory.band import credentials
from factory.seats import Seat, load_seats

LIMIT = re.compile(r"rate.?limit|usage.?limit|quota|429|resource.?exhausted|overloaded|too many requests", re.I)
RUNTIME_NOTE = """
## This run

- Repository (absolute path): {repo}
- Python for every command: {repo}/.venv/bin/python (it has the factory tools installed)
- Task package, read-only: {kickoff}
"""
CLAUDE_BASH = ["git", "docker", "python", "python3", ".venv/bin/python", "pytest", "uv", "pip", "npm", "npx",
               "node", "ls", "cat", "head", "tail", "wc", "grep", "find", "sed", "mkdir", "cp", "mv", "touch",
               "curl", "sleep", "diff", "sort", "jq", "echo", "pwd", "test", "chmod"]


def standing_instructions(repo: Path, seat: Seat, kickoff: Path | None) -> str:
    mandate = (repo / "mandates" / f"{seat.key}.md").read_text()
    return mandate + RUNTIME_NOTE.format(repo=repo, kickoff=kickoff or "named in the dispatch")


def claude_settings(repo: Path) -> dict:
    """Project permission rules for Claude Code seats (`.claude/settings.json` in the repo).
    With `dontAsk`, anything not allowed here is denied rather than asked about."""
    bash = [f"Bash({cmd}:*)" for cmd in CLAUDE_BASH] + [f"Bash({repo}/.venv/bin/python:*)"]
    return {"permissions": {"allow": ["Read", "Write", "Edit", "MultiEdit", "Glob", "Grep", "TodoWrite", *bash],
                            "deny": ["Bash(rm -rf:*)", "Bash(git push:*)", "Bash(git reset --hard:*)",
                                     "Bash(git rebase:*)", "Bash(git commit --amend:*)", "WebFetch", "WebSearch"]}}


def split_model(seat: Seat, model: str) -> tuple[str, str]:
    """`ollama:qwen3:8b` -> (ollama, qwen3:8b); a bare id uses the seat's provider."""
    provider, sep, rest = model.partition(":")
    if sep and provider in ("ollama", "google", "groq", "featherless"):
        return provider, rest
    return seat.provider or "google", model


def claude_config(seat: Seat, repo: Path, kickoff: Path | None, model: str) -> dict:
    return dict(model=model, custom_section=standing_instructions(repo, seat, kickoff), effort=seat.effort,
                permission_mode="dontAsk", cwd=str(repo), turn_timeout_s=3600.0,
                setting_sources=("project",), cli=dict(add_dirs=tuple(str(p) for p in [kickoff] if p)))


def opencode_config(seat: Seat, repo: Path, kickoff: Path | None, model: str, base_url: str) -> dict:
    if not repo.is_absolute():
        raise ValueError("--repo must be absolute: a relative path makes the seat commit somewhere else")
    provider, model_id = split_model(seat, model)
    return dict(base_url=base_url, directory=str(repo), provider_id=provider, model_id=model_id,
                custom_section=standing_instructions(repo, seat, kickoff), approval_mode="auto_accept",
                question_mode="auto_reject", turn_timeout_s=1800.0)


def codex_config(seat: Seat, repo: Path, kickoff: Path | None, model: str) -> dict:
    """Codex on the local ChatGPT login: never asks for approval; the sandbox lets it write
    only the repo and tool caches, with network on for Docker and the services under test."""
    home = Path.home()
    # `.git` is read-only inside a writable root unless named itself; seats commit their own work.
    roots = [str(repo), str(repo / ".git"), str(home / ".docker"), str(home / ".cache"), "/tmp"]
    return dict(model=model, workspace_for_room=lambda _room: str(repo),
                custom_section=standing_instructions(repo, seat, kickoff),
                approval_policy="never", approval_mode="auto_decline", turn_timeout_s=3600.0,
                sandbox_policy={"type": "workspace-write", "writableRoots": roots, "networkAccess": True})


def build_adapter(seat: Seat, repo: Path, kickoff: Path | None, model: str, opencode_url: str):
    from band.core.types import Emit

    if seat.harness == "Claude Code":
        from band.adapters import ClaudeSDKAdapter, ClaudeSDKAdapterConfig
        from band.adapters.claude_sdk import ClaudeCLIOptions
        cfg = claude_config(seat, repo, kickoff, model)
        cfg["cli"] = ClaudeCLIOptions(**cfg["cli"])
        return ClaudeSDKAdapter(ClaudeSDKAdapterConfig(**cfg), emit=Emit.TOOL_CALLS | Emit.USAGE)
    if seat.harness == "OpenCode":
        from band.adapters import OpencodeAdapter, OpencodeAdapterConfig
        return OpencodeAdapter(config=OpencodeAdapterConfig(**opencode_config(seat, repo, kickoff, model, opencode_url)),
                               emit={Emit.TOOL_CALLS, Emit.TASK_EVENTS, Emit.USAGE})
    if seat.harness == "Codex":
        from band.adapters.codex import CodexAdapter, CodexAdapterConfig
        return CodexAdapter(config=CodexAdapterConfig(**codex_config(seat, repo, kickoff, model)))
    raise ValueError(f"seat {seat.key!r}: no runtime for harness {seat.harness!r}")


async def run_once(seat: Seat, repo: Path, kickoff: Path | None, model: str, opencode_url: str):  # pragma: no cover
    from band import Agent

    agent_id, api_key = credentials(seat.key, dict(os.environ))
    agent = Agent.create(adapter=build_adapter(seat, repo, kickoff, model, opencode_url),
                         agent_id=agent_id, api_key=api_key)
    print(f"[{seat.key}] online with {seat.harness} / {model}", flush=True)
    await agent.run()


def next_model(models: list[str], index: int, error: str) -> tuple[int, float]:
    """On a limit, move down the fallback list and back off; otherwise retry the same model."""
    if LIMIT.search(error):
        return min(index + 1, len(models) - 1), 60.0
    return index, 10.0


def supervise(seat: Seat, repo: Path, kickoff: Path | None, opencode_url: str, max_restarts: int = 50):  # pragma: no cover
    """Run the seat forever; on any exit wait, then re-exec this process so every restart is a
    fresh interpreter (a fixed install or a cached failed import cannot linger). A seat that
    stayed up 15 minutes starts its count and model choice afresh."""
    import signal

    stopping = []

    def stop(_signum, _frame):
        stopping.append(True)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    models = [seat.model, *seat.fallbacks]
    index = int(os.environ.get("REDLINE_MODEL_INDEX", "0"))
    restarts = int(os.environ.get("REDLINE_RESTARTS", "0"))
    started = time.monotonic()
    error = "returned"
    try:
        asyncio.run(run_once(seat, repo, kickoff, models[index], opencode_url))
    except KeyboardInterrupt:
        return
    except Exception as exc:  # the seat must outlive any single failure
        error = f"{type(exc).__name__}: {str(exc)[:160]}"
    if stopping:  # a deliberate stop (SIGTERM) ends the seat; only failures restart it
        return
    if time.monotonic() - started > 900:
        index, restarts = 0, 0
    index, wait = next_model(models, index, error)
    restarts += 1
    wait *= min(2 ** (restarts - 1), 16)
    if restarts > max_restarts:
        print(f"[{seat.key}] gave up after {max_restarts} restarts", flush=True)
        return
    print(f"[{seat.key}] stopped ({error}); restart {restarts} in {wait:.0f}s on {models[index]}", flush=True)
    time.sleep(wait)
    os.environ.update(REDLINE_MODEL_INDEX=str(index), REDLINE_RESTARTS=str(restarts))
    os.execv(sys.executable, [sys.executable, "-m", "factory.seat", *sys.argv[1:]])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("seat")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--kickoff", type=Path)
    parser.add_argument("--opencode-url", default="http://127.0.0.1:4096")
    args = parser.parse_args(argv)
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    seat = load_seats()[args.seat]
    if not args.repo.is_absolute():
        parser.error("--repo must be absolute")
    standing_instructions(args.repo, seat, args.kickoff)  # fail fast if the mandate is missing
    supervise(seat, args.repo, args.kickoff, args.opencode_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
