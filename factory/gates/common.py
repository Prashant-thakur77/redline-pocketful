"""Shared plumbing for gate scripts: logs, ledger events, the offline service."""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import httpx

from factory.events import Event
from factory.ledger import Ledger

CPUS, MEMORY, PORT = "2", "2g", "8080"
HEALTH_TIMEOUT = 60.0


class GateError(RuntimeError):
    pass


def repo_root(path: Path) -> Path:
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True)
    return Path(proc.stdout.strip()) if proc.returncode == 0 else path.resolve().parent


def stage_number(stage_dir: Path) -> int | None:
    match = re.search(r"(\d+)$", stage_dir.resolve().name)
    return int(match.group(1)) if match else None


def head_commit(path: Path) -> str:
    proc = subprocess.run(["git", "-C", str(path), "rev-parse", "--short=12", "HEAD"],
                          capture_output=True, text=True)
    return proc.stdout.strip() if proc.returncode == 0 else "uncommitted"


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("stage_dir", type=Path, help="the service folder")
    parser.add_argument("--stage", type=int, help="default: trailing number of the folder name")
    parser.add_argument("--node", default="adhoc", help="work item id, for the ledger")
    parser.add_argument("--evidence", type=Path, help="default: <repo>/evidence")
    parser.add_argument("--base-url", help="reuse a running service instead of building one")
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--health-timeout", type=float, default=HEALTH_TIMEOUT)
    return parser


class Gate:
    """One gate run: a log file, a printed verdict and a ledger event."""

    def __init__(self, gate: str, args: argparse.Namespace):
        self.gate = gate
        self.stage_dir = args.stage_dir.resolve()
        self.stage = args.stage if args.stage is not None else stage_number(self.stage_dir)
        self.node = args.node
        self.root = repo_root(self.stage_dir)
        self.evidence = (args.evidence or self.root / "evidence").resolve()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        folder = self.evidence / "gates" / f"s{self.stage if self.stage is not None else 'x'}"
        folder.mkdir(parents=True, exist_ok=True)
        self.log_path = folder / f"{self.node}-{gate}-{stamp}-{uuid.uuid4().hex[:4]}.log"
        self.lines: list[str] = []

    def log(self, *lines: str):
        for line in lines:
            self.lines.append(line)
            self.log_path.write_text("\n".join(self.lines) + "\n")

    def finish(self, passed: bool, detail: str, **extra) -> int:
        self.log("", f"RESULT: {'PASS' if passed else 'FAIL'} — {detail}")
        try:
            log = str(self.log_path.relative_to(self.root))
        except ValueError:
            log = str(self.log_path)
        Ledger(self.evidence / "ledger.jsonl").append(Event(
            kind="gate_result", seat=os.environ.get("REDLINE_SEAT", "verifier"), stage=self.stage, node=self.node,
            source=f"gate:{self.gate}:{self.log_path.name}",
            payload={"gate": self.gate, "passed": passed, "detail": detail[:500], "log": log,
                     "commit": head_commit(self.stage_dir), **extra}))
        print(f"{self.gate}: {'PASS' if passed else 'FAIL'} — {detail}\n  log: {log}")
        return 0 if passed else 1


def run(cmd: list[str], timeout: float = 600, cwd: Path | None = None, env: dict | None = None,
        gate: Gate | None = None) -> subprocess.CompletedProcess:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, env=env)
    except subprocess.TimeoutExpired as exc:
        # TimeoutExpired carries raw bytes even in text mode; decode before anything joins it with str
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        proc = subprocess.CompletedProcess(cmd, 124, out, f"timed out after {timeout}s")
    if gate:
        gate.log(f"$ {' '.join(map(str, cmd))}  (exit {proc.returncode})",
                 (proc.stdout or "")[-6000:], (proc.stderr or "")[-4000:])
    return proc


class Service:
    """Build a folder's Dockerfile and run it like a judge would: no outbound
    network, 2 vCPU, 2 GiB, PORT=8080. Reachable from the host by container IP."""

    def __init__(self, folder: Path, gate: Gate | None = None, health_path: str = "/health",
                 tag: str | None = None):
        self.folder = Path(folder).resolve()
        self.gate = gate
        self.health_path = health_path
        digest = hashlib.sha1(str(self.folder).encode()).hexdigest()[:10]
        self.tag = tag or f"redline-gate-{digest}"
        self.network = f"redline-net-{uuid.uuid4().hex[:10]}"
        self.container: str | None = None
        self.base_url: str | None = None

    def build(self, timeout: float = 900):
        if not (self.folder / "Dockerfile").is_file():
            raise GateError(f"{self.folder}/Dockerfile is missing")
        proc = run(["docker", "build", "--label", "redline-gate=1", "-t", self.tag, str(self.folder)],
                   timeout, gate=self.gate)
        if proc.returncode != 0:
            raise GateError(f"docker build failed (exit {proc.returncode})")

    def start(self, timeout: float = HEALTH_TIMEOUT):
        run(["docker", "network", "create", "--internal", self.network], 60, gate=self.gate)
        proc = run(["docker", "run", "-d", "--network", self.network, "--cpus", CPUS,
                    "--memory", MEMORY, "-e", f"PORT={PORT}", self.tag], 120, gate=self.gate)
        if proc.returncode != 0:
            raise GateError("container did not start")
        self.container = proc.stdout.strip()
        ip = run(["docker", "inspect", "-f",
                  "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", self.container]).stdout.strip()
        self.base_url = f"http://{ip}:{PORT}"
        self.wait_healthy(timeout)
        return self.base_url

    def wait_healthy(self, timeout: float):
        deadline, last = time.monotonic() + timeout, "no response"
        while time.monotonic() < deadline:
            state = run(["docker", "inspect", "-f", "{{.State.Running}}", self.container]).stdout.strip()
            if state != "true":
                raise GateError(f"container exited before healthy:\n{self.logs()}")
            try:
                r = httpx.get(self.base_url + self.health_path, timeout=2)
                if r.status_code == 200:
                    return
                last = f"HTTP {r.status_code}"
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            time.sleep(0.5)
        raise GateError(f"not healthy within {timeout:.0f}s (last: {last})\n{self.logs()}")

    def logs(self) -> str:
        if not self.container:
            return ""
        proc = run(["docker", "logs", "--tail", "60", self.container])
        return (proc.stdout + proc.stderr)[-4000:]

    def stop(self):
        if self.container:
            if self.gate:
                self.gate.log("--- service log (tail) ---", self.logs())
            run(["docker", "rm", "-f", self.container], 60)
        run(["docker", "network", "rm", self.network], 60)
        self.container = None

    def __enter__(self):
        self.build()
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


def prune_images():
    """Remove gate images left dangling by rebuilt tags; only ones the gates labelled."""
    run(["docker", "image", "prune", "-f", "--filter", "label=redline-gate=1"], 120)


def failure(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()
    return f"{type(exc).__name__}: {text[0][:300] if text else ''}"


def run_gate(gate: Gate, args, check) -> int:
    """Run `check(base_url)` against `--base-url`, or against a freshly built offline
    service. Any exception fails the gate with a ledger event instead of crashing."""
    if args.base_url:
        try:
            return check(args.base_url)
        except Exception as exc:
            return gate.finish(False, failure(exc))
    service = Service(gate.stage_dir, gate, args.health_path)
    try:
        service.build()
        return check(service.start(args.health_timeout))
    except Exception as exc:
        return gate.finish(False, failure(exc))
    finally:
        service.stop()


def pytest_counts(junit: Path) -> dict:
    try:
        root = ET.parse(junit).getroot()
    except (OSError, ET.ParseError):
        return {"tests": 0, "failures": 0, "errors": 1, "skipped": 0}
    suites = [root] if root.tag == "testsuite" else list(root)
    total = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in total:
            total[key] += int(suite.get(key, 0))
    return total


def run_pytest(paths: list[Path], base_url: str, gate: Gate, timeout: float = 2400,
               extra: list[str] | None = None) -> dict:
    junit = gate.log_path.with_suffix(".junit.xml")
    env = {**__import__("os").environ, "BASE_URL": base_url, "PYTHONDONTWRITEBYTECODE": "1"}
    cmd = [sys.executable, "-m", "pytest", *map(str, paths), "-q", "-p", "no:cacheprovider",
           f"--junitxml={junit}", *(extra or [])]
    proc = run(cmd, timeout, env=env, gate=gate)
    counts = pytest_counts(junit)
    counts["exit"] = proc.returncode
    counts["timed_out"] = proc.returncode == 124
    counts["passed"] = counts["tests"] - counts["failures"] - counts["errors"] - counts["skipped"]
    return counts


def green(counts: dict) -> bool:
    """Zero tests, a skip, an error or a failure can never pass a gate."""
    return (counts["exit"] == 0 and counts["tests"] > 0 and counts["failures"] == 0
            and counts["errors"] == 0 and counts["skipped"] == 0)
