"""One-screen view of a run: the room's messages (sender and first line) and the
result repo's commits. Reads only; never posts.

    python -m factory.watch --room <id> --repo /abs/result [--last 30]
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from factory.band import BandAgent, credentials

REPO = Path(__file__).resolve().parent.parent


def lines(items: list[dict], last: int) -> list[str]:
    out = []
    for m in items:
        if m.get("message_type") != "text":
            continue
        text = re.sub(r"```json[\s\S]*?```", "[evidence]", str(m.get("content", "")))
        text = re.sub(r"@\[\[[^\]]+\]\]", "@", re.sub(r"\s+", " ", text))
        out.append(f"{str(m.get('inserted_at', ''))[11:19]} {m.get('sender_name')}: {text[:220]}")
    return out[-last:]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--room", required=True)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--last", type=int, default=30)
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env")
    agent_id, key = credentials("planner", dict(os.environ))
    agent = BandAgent("planner", agent_id, key)
    try:
        items = agent.context(args.room)
    finally:
        agent.close()
    print("\n".join(lines(items, args.last)))
    print(f"-- {len(items)} room events")
    if args.repo:
        log = subprocess.run(["git", "-C", str(args.repo), "log", "--format=%h %an: %s", "-15"],
                             capture_output=True, text=True).stdout
        print(log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
