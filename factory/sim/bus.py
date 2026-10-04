"""A local stand-in for a BAND room, enforcing the rules that shape handoffs:

- a seat only receives messages that @mention it
- every message must mention at least one other participant
- a seat may not mention itself (BAND answers 422)
- `@handle` is stored as `@[[participant-id]]`, as in the console download

`save()` writes the room in the console download's shape, so the same ingest,
report and submission checks read it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HANDLE = re.compile(r"(?<![\w@])@([a-z][a-z0-9_-]*)")


class MentionError(ValueError):
    """What BAND would reject: no peer mentioned, or a self-mention."""


@dataclass
class Participant:
    key: str
    name: str
    agent: bool = True

    @property
    def id(self) -> str:
        return f"p-{self.key}"


@dataclass
class Room:
    participants: dict[str, Participant]
    messages: list[dict] = field(default_factory=list)
    unread: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def with_seats(cls, seats: dict[str, str], human: str = "Human") -> "Room":
        people = {k: Participant(k, name) for k, name in seats.items()}
        people["human"] = Participant("human", human, agent=False)
        return cls(people, unread={k: [] for k in people})

    def post(self, sender: str, text: str) -> dict:
        handles = [h for h in HANDLE.findall(text) if h in self.participants]
        if sender in handles:
            raise MentionError(f"{sender} cannot mention itself (422 cannot_mention_self)")
        if not handles:
            raise MentionError("a message must mention at least one other participant")
        content = HANDLE.sub(lambda m: f"@[[{self.participants[m.group(1)].id}]]"
                             if m.group(1) in self.participants else m.group(0), text)
        who = self.participants[sender]
        message = {"id": f"m{len(self.messages) + 1}", "senderId": who.id, "senderName": who.name,
                   "senderType": "Agent" if who.agent else "User", "messageType": "text",
                   "content": content, "insertedAt": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.messages.append(message)
        for handle in dict.fromkeys(handles):
            self.unread[handle].append(len(self.messages) - 1)
        return message

    def inbox(self, seat: str) -> list[dict]:
        """Messages addressed to `seat` since it last looked, with handles restored."""
        items = [self.readable(self.messages[i]) for i in self.unread[seat]]
        self.unread[seat] = []
        return items

    def readable(self, message: dict) -> dict:
        by_id = {p.id: p.key for p in self.participants.values()}
        text = re.sub(r"@\[\[([^\]]+)\]\]", lambda m: f"@{by_id.get(m.group(1), m.group(1))}", message["content"])
        return {**message, "content": text}

    def human_messages(self) -> int:
        return sum(1 for m in self.messages if m["senderType"] == "User")

    def save(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"scope": "full", "source": "factory.sim", "messages": self.messages},
                                         indent=2, ensure_ascii=False))
