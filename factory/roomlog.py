"""Read a room log in either shape: the Band console download (`room.json`)
or our own export. Normalises to one message dict per message."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

MENTION = re.compile(r"@\[\[([^\]]+)\]\]")


@dataclass
class Message:
    id: str
    sender_id: str
    sender: str
    agent: bool
    kind: str
    content: str
    ts: str
    mentions: list[str]
    metadata: dict


def _get(m: dict, *keys, default=""):
    for key in keys:
        if m.get(key) not in (None, ""):
            return m[key]
    return default


def read_text(path: Path | str) -> str:
    """Room logs may be stored gzipped (`.gz`): smaller, and out of reach of config-file scanners."""
    path = Path(path)
    if path.suffix == ".gz":
        import gzip
        return gzip.decompress(path.read_bytes()).decode()
    return path.read_text()


def load(path: Path | str) -> list[Message]:
    raw = json.loads(read_text(path))
    items = raw.get("messages") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"{path}: expected a `messages` list")
    out = []
    for i, m in enumerate(items):
        content = str(_get(m, "content", "text"))
        out.append(Message(
            id=str(_get(m, "id", "messageId", default=f"idx{i}")),
            sender_id=str(_get(m, "senderId", "sender_id")),
            sender=str(_get(m, "senderName", "sender_name")),
            agent=str(_get(m, "senderType", "sender_type")).lower() == "agent",
            kind=str(_get(m, "messageType", "message_type", default="text")),
            content=content,
            ts=utc(str(_get(m, "insertedAt", "inserted_at", "createdAt", "created_at", "timestamp"))),
            mentions=MENTION.findall(content),
            metadata=m.get("metadata") if isinstance(m.get("metadata"), dict) else {}))
    return out


def utc(ts: str) -> str:
    """ISO-8601 with an explicit UTC offset, so naive and aware stamps compare safely."""
    from datetime import datetime, timezone
    if not ts:
        return ts
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return ts
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def seat_names(messages: list[Message]) -> dict[str, str]:
    """{participant id: display name} for every agent that spoke."""
    return {m.sender_id: m.sender for m in messages if m.agent and m.sender_id}


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())
