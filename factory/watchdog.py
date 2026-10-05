"""Usage-limit watchdog: pause and resume a seat's work with no human input.

When a model limit makes BAND mark a message as failed, the seat that should
have acted goes quiet and nobody mentions it again: the run stalls. This
process watches the seat logs; on such a failure it records the pause in the
ledger, waits until the seat's model answers a one-word probe again, and then,
as that seat, asks the sender to resend the lost message.

    python -m factory.watchdog --room <room id> --repo /abs/result [--logs ~/.cache/redline/logs]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv

from factory.band import BandAgent, credentials
from factory.events import Event
from factory.ledger import Ledger
from factory.seats import Seat, load_seats

REPO = Path(__file__).resolve().parent.parent
FAILED = re.compile(r"Marking message (\S+) as failed: (.*)")
RESYNC = re.compile(r"Catching up missed message (\S+) via /next resync")
WORK = re.compile(r"Tool call:|Complete - ")
SENT = re.compile(r"Tool call: band_send_message")
SILENT_FOR = 600  # a lost reply matters only if no seat says anything for this long afterwards
STUCK_AFTER = 300  # the same catch-up repeated this often, with no work between, is a hung runtime
LIMIT = re.compile(r"usage limit|limit reached|hit your limit|rate.?limit|quota|overloaded|429", re.I)
LOST = re.compile(r"without calling band_send_message|nothing reached the room", re.I)
STAMP = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
TURN_START = re.compile(r"Sending query to Claude SDK|Tool call:")
TURN_END = re.compile(r"Complete - |Marking message \S+ as failed")  # "no reply this turn" is a tool call, mid-turn
NET_DOWN = re.compile(r"name resolution|Network is unreachable|ConnectError")
NET_BACK = re.compile(r"WebSocket reconnected")
LOCAL_WORK = re.compile(r"factory\.gates|pytest|harness run")
UNREPORTED_AFTER = 900  # a seat's commit followed by this long of room silence was never reported


def limit_failures(lines: list[str]) -> list[tuple[str, str]]:
    """(message id, reason) for every message BAND failed because of a model limit, or because the
    seat's turn ended without a send (acted on only if the room then stays silent: see main)."""
    found = []
    for line in lines:
        match = FAILED.search(line)
        if match and (LIMIT.search(match.group(2)) or LOST.search(match.group(2))):
            found.append((match.group(1), match.group(2).strip()[:200]))
    return found


def stuck_on(lines: list[str], streak: dict) -> str | None:
    """Track repeated resync of one message with no work in between; return its id once hung."""
    for line in lines:
        if WORK.search(line):
            streak.clear()
            continue
        match = RESYNC.search(line)
        if match:
            streak[match.group(1)] = streak.get(match.group(1), 0) + 1
            if streak[match.group(1)] >= STUCK_AFTER:
                streak.clear()
                return match.group(1)
    return None


def last_send_time(lines: list[str]) -> float | None:
    """Epoch time of the last send-tool call in a seat log (log stamps are local time)."""
    for line in reversed(lines):
        if SENT.search(line) and (stamp := STAMP.match(line)):
            return dt.datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M:%S").timestamp()
    return None


def in_turn(lines: list[str], busy: bool) -> bool:
    """Whether a seat is mid-turn after these log lines: a long turn (writing a test suite)
    keeps the room quiet without anything being lost."""
    for line in lines:
        if TURN_START.search(line):
            busy = True
        elif TURN_END.search(line):
            busy = False
    return busy


def unreported(head: tuple[str, str, float, str] | None, last_send: float, now: float,
               seats: dict[str, Seat]) -> str | None:
    """The seat key whose newest commit came after the room's last message and has gone
    unreported for UNREPORTED_AFTER seconds: the work is done but nobody was told."""
    if head is None:
        return None
    _, author, when, _ = head
    key = next((k for k, seat in seats.items() if seat.name == author), None)
    if key and when > last_send and now - when > UNREPORTED_AFTER:
        return key
    return None


def seat_commits(repo: Path, names: set[str]) -> list[tuple[str, str, float, str]]:
    """Each seat's newest recent commit, newest first (factory maintenance commits are skipped)."""
    proc = subprocess.run(["git", "-C", str(repo), "log", "-50", "--format=%h%x00%an%x00%ct%x00%s"],
                          capture_output=True, text=True)
    found, seen = [], set()
    for line in proc.stdout.splitlines():
        parts = line.split("\0")
        if len(parts) == 4 and parts[1] in names and parts[1] not in seen:
            seen.add(parts[1])
            found.append((parts[0], parts[1], float(parts[2]), parts[3]))
    return found


def report_request(asker: Seat, seat: Seat, room: str, sha: str, subject: str):  # pragma: no cover - live BAND
    """As `asker`, ask `seat` to post the result its commit records."""
    agent_id, key = credentials(asker.key, dict(os.environ))
    agent = BandAgent(asker.key, agent_id, key)
    try:
        seat_id = credentials(seat.key, dict(os.environ))[0]
        target = next((p for p in agent.participants(room) if p.get("id") == seat_id), None)
        if target is None:
            return
        text = (f"@{target.get('handle') or target.get('name')} your commit {sha} (\"{subject[:120]}\") "
                f"never reached the room. Post its result and hand off so the run can go on.")
        agent.send(room, text, [{"id": target["id"], "handle": target.get("handle"), "name": target.get("name")}])
    finally:
        agent.close()


def network_recovered(lines: list[str], down: bool) -> tuple[bool, bool]:
    """(still down, just recovered) after these log lines: turns that were running when the host lost
    its network never come back on their own, so a reconnect after an outage restarts the seats."""
    recovered = False
    for line in lines:
        if NET_DOWN.search(line):
            down = True
        elif NET_BACK.search(line) and down:
            down, recovered = False, True
    return down, recovered


def running_local_work(key: str) -> bool:  # pragma: no cover - reads ps
    """True when the seat's process group is running a gate or test command: that turn is busy on
    local work an outage cannot touch, and restarting the seat would kill it."""
    proc = subprocess.run(["ps", "-eo", "pgid,args"], capture_output=True, text=True)
    groups = {line.split(None, 1)[0] for line in proc.stdout.splitlines()
              if f"factory.seat {key} " in line and line.split(None, 1)[0].isdigit()}
    return any(line.split(None, 1)[0] in groups and LOCAL_WORK.search(line)
               for line in proc.stdout.splitlines() if line.strip())


def restart_seat(key: str, repo: Path, kickoff: Path):  # pragma: no cover - process control
    import sys
    subprocess.run([sys.executable, "-m", "factory.launch", "--stop", "--seats", key], cwd=REPO, timeout=120)
    subprocess.run([sys.executable, "-m", "factory.launch", "--detach", "--seats", key, "--repo", str(repo),
                    "--kickoff", str(kickoff)], cwd=REPO, timeout=120)


def model_answers(seat: Seat) -> bool:
    if seat.harness != "Claude Code":
        return True  # OpenCode/Codex seats fall back to other models on their own
    proc = subprocess.run(["claude", "-p", "Reply with: ok", "--model", seat.model, "--output-format", "text"],
                          capture_output=True, text=True, timeout=180)
    return proc.returncode == 0 and not LIMIT.search(proc.stdout + proc.stderr)


def resend_request(seat: Seat, room: str, message_id: str) -> str | None:  # pragma: no cover - live BAND
    agent_id, key = credentials(seat.key, dict(os.environ))
    agent = BandAgent(seat.key, agent_id, key)
    try:
        message = next((m for m in agent.context(room) if m.get("id") == message_id), None)
        if message is None or message.get("sender_id") == agent_id:
            return None
        people = {p.get("id"): p for p in agent.participants(room)}
        sender = people.get(message["sender_id"], {"id": message["sender_id"], "name": message.get("sender_name")})
        handle = sender.get("handle") or sender.get("name")
        text = (f"@{handle} my reply to your message from {str(message.get('inserted_at', ''))[11:16]} UTC "
                f"never reached the room (paused by a usage limit, or answered outside the send tool). "
                f"Please resend it so I can act on it.")
        agent.send(room, text, [{"id": sender["id"], "handle": sender.get("handle"), "name": sender.get("name")}])
        return handle
    finally:
        agent.close()


def record(ledger: Ledger, seat: str, passed: bool, detail: str):
    ledger.append(Event(kind="gate_result", seat=seat, source=f"watchdog:{seat}:{int(time.time())}",
                        payload={"gate": "g8", "passed": passed, "detail": detail}))


def main(argv=None) -> int:  # pragma: no cover - long-running
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--room", required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--logs", type=Path, default=Path.home() / ".cache" / "redline" / "logs")
    parser.add_argument("--first-wait", type=float, default=600)
    parser.add_argument("--kickoff", type=Path, default=REPO.parent / "dark-factory-wearedevs")
    parser.add_argument("--from-start", action="store_true",
                        help="also recover failures logged before the watchdog started (only this room's)")
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env")
    seats = load_seats()
    ledger = Ledger(args.repo / "evidence" / "ledger.jsonl")
    offsets = {k: 0 if args.from_start else ((args.logs / f"{k}.log").stat().st_size
                                             if (args.logs / f"{k}.log").exists() else 0) for k in seats}
    handled: set[str] = set()
    backlog = {k: args.from_start for k in seats}  # the first read of an old log never counts as a live hang
    streaks: dict[str, dict] = {k: {} for k in seats}
    lost: dict[str, tuple[str, str, float]] = {}  # message id -> (seat, reason, when seen)
    last_send = 0.0
    for key in seats:  # the room's last message, from every seat's full log
        log = args.logs / f"{key}.log"
        if log.exists():
            last_send = max(last_send, last_send_time(log.read_text(errors="replace").splitlines()) or 0.0)
    nudged: set[str] = set()
    net_down = False
    busy = {k: in_turn((args.logs / f"{k}.log").read_text(errors="replace").splitlines(), False)
            if (args.logs / f"{k}.log").exists() else False for k in seats}
    print(f"watchdog on room {args.room}", flush=True)
    while True:
        for key, seat in seats.items():
            log = args.logs / f"{key}.log"
            if not log.exists():
                continue
            with open(log, errors="replace") as fh:
                fh.seek(offsets[key])
                lines = fh.read().splitlines()
                offsets[key] = fh.tell()
            last_send = max(last_send, last_send_time(lines) or 0.0)
            if key == "planner":
                net_down, recovered = network_recovered(lines, net_down)
                if recovered:
                    print("network back after an outage; restarting every seat", flush=True)
                    record(ledger, "planner", False, "host network outage interrupted running turns")
                    for name in seats:
                        if running_local_work(name):
                            print(f"[{name}] busy on a gate or test run; not restarted", flush=True)
                            continue
                        restart_seat(name, args.repo, args.kickoff)
                    record(ledger, "planner", True, "network back; every seat restarted to resume its work")
                    offsets = {k: (args.logs / f"{k}.log").stat().st_size if (args.logs / f"{k}.log").exists() else 0
                               for k in seats}
                    break
            busy[key] = in_turn(lines, busy[key])
            hung = None if backlog[key] else stuck_on(lines, streaks[key])
            backlog[key] = False
            if hung:
                print(f"[{key}] runtime hung re-syncing {hung}; restarting the seat", flush=True)
                record(ledger, key, False, f"{key} runtime hung re-syncing a message; restarted the seat")
                restart_seat(key, args.repo, args.kickoff)
                offsets[key] = log.stat().st_size
                continue
            for message_id, reason in limit_failures(lines):
                if message_id in handled:
                    continue
                handled.add(message_id)
                if not LIMIT.search(reason):  # a turn with no send: wait and see if the room goes silent
                    lost[message_id] = (key, reason, time.time())
                    continue
                print(f"[{key}] lost message {message_id}: {reason}", flush=True)
                wait = args.first_wait
                while LIMIT.search(reason) and not model_answers(seat):
                    time.sleep(wait)
                    wait = min(wait * 1.5, 3600)
                sender = resend_request(seat, args.room, message_id)
                if sender is None:  # not this room's message, or the seat's own: nothing to recover
                    continue
                record(ledger, key, False, f"{key} lost a message: {reason}")
                record(ledger, key, True, f"{key} recovered; asked {sender} to resend")
                print(f"[{key}] recovered; asked {sender} to resend", flush=True)
        for message_id, (key, reason, seen) in list(lost.items()):
            if last_send > seen:  # the band kept talking: that seat just had nothing to add
                del lost[message_id]
            elif time.time() - seen > SILENT_FOR:
                del lost[message_id]
                sender = resend_request(seats[key], args.room, message_id)
                if sender:
                    record(ledger, key, False, f"{key} lost a reply and the room went silent: {reason}")
                    record(ledger, key, True, f"{key} recovered; asked {sender} to resend")
                    print(f"[{key}] room silent after a lost reply; asked {sender} to resend", flush=True)
        for head in seat_commits(args.repo, {seat.name for seat in seats.values()}):
            quiet = unreported(head, last_send, time.time(), seats)
            if not quiet or head[0] in nudged or any(busy.values()):
                continue
            nudged.add(head[0])
            asker = seats["planner"] if quiet != "planner" else seats["verifier"]
            report_request(asker, seats[quiet], args.room, head[0], head[3])
            record(ledger, quiet, False, f"{quiet} committed {head[0]} but never reported it to the room")
            record(ledger, quiet, True, f"{asker.key} asked {quiet} to post the result of {head[0]}")
            print(f"[{quiet}] commit {head[0]} unreported; {asker.key} asked for the result", flush=True)
        time.sleep(30)


if __name__ == "__main__":
    raise SystemExit(main())
