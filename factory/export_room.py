"""Pull a room's full context through the BAND API (every page, following
`next_cursor`), redact credential shapes, and write it in the console download's
shape to `evidence/room-export.json.gz`.

The submitted `room.json` is always the Band console's own download, saved
unchanged; this export feeds the ledger and reports during and after a run.

    python -m factory.export_room --room <room id> [--seat planner] [--out evidence/room-export.json.gz]
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

from factory.band import BandAgent, credentials

REDACT = [
    r"(?i)\bbearer\s+(?=[A-Za-z0-9._\-]*\d)[A-Za-z0-9._\-]{20,}",
    r"\bsk-[A-Za-z0-9._\-]{16,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD))(\s*=\s*)[^\s\"']+",
    r"""(?<=://)[^/\s:@"'\\]+:[^/\s@"'\\]+(?=@)""",
]


def redact(text: str) -> str:
    for pattern in REDACT:
        text = re.sub(pattern, lambda m: (m.group(1) + m.group(2) + "[REDACTED]") if m.re.groups >= 2
                      else "[REDACTED]", text)
    return text


def to_console(items: list[dict]) -> dict:
    messages = [{
        "id": m.get("id"),
        "senderId": m.get("sender_id"),
        "senderName": m.get("sender_name"),
        "senderType": m.get("sender_type"),
        "messageType": m.get("message_type"),
        "content": redact(str(m.get("content", ""))),
        "insertedAt": m.get("inserted_at"),
        "metadata": m.get("metadata") or {},
    } for m in items]
    return {"scope": "full", "source": "factory.export_room", "messages": messages}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--room", required=True)
    parser.add_argument("--seat", default="planner", help="whose credentials read the room")
    parser.add_argument("--out", type=Path, default=Path("evidence/room-export.json.gz"))
    args = parser.parse_args(argv)
    if args.out.name == "room.json":
        parser.error("room.json is the Band console download, saved unchanged; write elsewhere")
    load_dotenv()
    agent_id, api_key = credentials(args.seat, dict(os.environ))
    agent = BandAgent(args.seat, agent_id, api_key)
    try:
        items = agent.context(args.room)
    finally:
        agent.close()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(to_console(items), indent=2, ensure_ascii=False)
    if args.out.suffix == ".gz":
        import gzip
        args.out.write_bytes(gzip.compress(body.encode()))
    else:
        args.out.write_text(body)
    print(f"{len(items)} messages -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
