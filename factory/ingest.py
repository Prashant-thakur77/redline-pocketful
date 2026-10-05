"""Turn a room log into ledger events: every agent message carrying an EVIDENCE
block becomes a `handoff` (plus a `verdict` and a `cost` when it has them).

Idempotent: a message already in the ledger (by `room:<id>`) is skipped, and a
verdict a seat already recorded itself is not counted twice.

    python -m factory.ingest room.json [--ledger evidence/ledger.jsonl]
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

from factory import roomlog
from factory.events import Event
from factory.ledger import Ledger
from factory.metrics import verdict_of
from factory.protocol import try_parse
from factory.seats import load_seats

VERDICTS = {"GO", "NEEDS_WORK", "BLOCK", "BREACH", "HOLDS"}


def seat_key(name: str) -> str:
    wanted = roomlog.slug(name)
    for key, seat in load_seats().items():
        if wanted in (roomlog.slug(key), roomlog.slug(seat.name)):
            return key
    return wanted or "unknown"


def stage_of(evidence) -> int | None:
    if evidence.stage is not None:
        return evidence.stage
    match = re.match(r"R-(\d+)-", evidence.req[0])
    return int(match.group(1)) if match else None


def ingest(room: Path, ledger: Ledger) -> int:
    messages = roomlog.load(room)
    names = roomlog.seat_names(messages)
    existing = ledger.events()
    seen = {e.source for e in existing}
    mine = [e for e in existing if e.kind == "verdict" and e.source.startswith("seat:")]
    recorded = Counter((e.stage, verdict_of(e), str(e.payload.get("commit") or "")[:7]) for e in mine)
    loose = Counter((e.stage, verdict_of(e)) for e in mine)
    added = 0
    # Measured usage (the runtime's own per-turn events) beats a seat's estimate in its evidence.
    usage_seen = any(isinstance((m.metadata or {}).get("band_usage"), dict) for m in messages)
    for m in messages:
        source = f"room:{m.id}"
        if not m.agent or source in seen:
            continue
        usage = (m.metadata or {}).get("band_usage")
        if isinstance(usage, dict):
            tokens = sum(int(usage.get(k, 0) or 0) for k in
                         ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens"))
            ledger.append(Event(kind="cost", seat=seat_key(m.sender), source=source,
                                payload={"tokens": tokens, "usage": usage}, **({"ts": m.ts} if m.ts else {})))
            added += 1
            continue
        if m.kind != "text":
            continue
        evidence = try_parse(m.content)
        if evidence is None:
            continue
        seat = seat_key(m.sender)
        to = [seat_key(names.get(i, i)) for i in m.mentions if i != m.sender_id]
        stage, node = stage_of(evidence), evidence.node
        base = dict(seat=seat, stage=stage, node=node, source=source, **({"ts": m.ts} if m.ts else {}))
        text = re.sub(r"```json[\s\S]*?```", "", m.content)
        text = roomlog.MENTION.sub(lambda x: "@" + seat_key(names.get(x.group(1), x.group(1))), text).strip()[:300]
        ledger.append(Event(kind="handoff", payload={"to": to, "evidence": evidence.model_dump(), "text": text},
                            **base))
        added += 1
        key = (stage, evidence.verdict, evidence.commit[:7])
        if evidence.verdict in VERDICTS:
            # The seat already recorded this verdict: same commit if known, else same stage and verdict.
            if recorded[key] > 0 or loose[(stage, evidence.verdict)] > 0:
                recorded[key] = max(recorded[key] - 1, 0)
                loose[(stage, evidence.verdict)] -= 1
            else:
                ledger.append(Event(kind="verdict", payload={"verdict": evidence.verdict, "to": to, "text": text,
                                                             "commit": evidence.commit}, **base))
                added += 1
        if not usage_seen and (evidence.cost.tokens or evidence.cost.usd or evidence.cost.seconds):
            ledger.append(Event(kind="cost", payload={**evidence.cost.model_dump(), "estimate": True}, **base))
            added += 1
    return added


LOG_TURN = re.compile(r"^(\S+ \S+) INFO band\.adapters\.claude_sdk: Room (\S+): Complete - (\d+)ms, \$([0-9.]+)")


def ingest_logs(logs: Path, room_id: str, ledger: Ledger) -> int:
    """Per-turn wall time and list-price spend from Claude seat logs (`<seat>.log`)."""
    from datetime import datetime, timezone
    seen = {e.source for e in ledger.events()}
    added = 0
    for log in sorted(Path(logs).glob("*.log")):
        total = 0.0  # the logged figure is the session's running total; a restart starts it again
        for number, line in enumerate(log.read_text(errors="replace").splitlines(), 1):
            match = LOG_TURN.match(line)
            if not match or match.group(2) != room_id:
                continue
            running = float(match.group(4))
            turn = running - total if running >= total else running
            total = running
            source = f"log:{log.stem}:{number}"
            if source in seen:
                continue
            local = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S,%f").astimezone(timezone.utc)
            ledger.append(Event(kind="cost", seat=log.stem, source=source, ts=local.isoformat(timespec="seconds"),
                                payload={"usd": round(turn, 4), "seconds": int(match.group(3)) / 1000}))
            added += 1
    return added


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("room", type=Path)
    parser.add_argument("--ledger", type=Path, default=Path("evidence/ledger.jsonl"))
    parser.add_argument("--logs", type=Path, help="seat log folder (e.g. ~/.cache/redline/logs) for per-turn spend")
    parser.add_argument("--room-id", help="room id whose turns to take from the logs")
    args = parser.parse_args(argv)
    ledger = Ledger(args.ledger)
    print(f"{ingest(args.room, ledger)} room events added")
    if args.logs and args.room_id:
        print(f"{ingest_logs(args.logs, args.room_id, ledger)} log cost events added")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
