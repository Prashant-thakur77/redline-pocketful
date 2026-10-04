"""Open a fresh room, add every seat, and send the one human dispatch to the
coordinator. Used for rehearsals; for the judged run a human may paste the
same text by hand instead.

    python -m factory.dispatch plan/dispatch-toy.md --title "Toy rehearsal" \
        --set REPO=/abs/result --set KICKOFF=/abs/task-package

`{{NAME}}` placeholders in the file are filled from `--set NAME=value`; an
unfilled placeholder stops the dispatch. Reads BAND_USER_API_KEY from .env.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from factory.band import credentials
from factory.seats import load_seats

REPO = Path(__file__).resolve().parent.parent
PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def render(template: str, values: dict[str, str]) -> str:
    text = PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)
    missing = sorted(set(PLACEHOLDER.findall(text)))
    if missing:
        raise ValueError(f"unfilled placeholders: {', '.join(missing)}")
    return text


def body_of(markdown: str) -> str:
    """The text between the first pair of ``` fences, or the whole file."""
    match = re.search(r"```(?:text|markdown)?\n([\s\S]*?)\n```", markdown)
    return match.group(1) if match else markdown


def send(text: str, title: str, coordinator: str = "planner") -> str:  # pragma: no cover - live BAND
    from band_rest import ChatMessageRequest, ChatMessageRequestMentionsItem, ParticipantRequest, RestClient
    from band_rest.human_api_chats import CreateMyChatRoomRequestChat

    client = RestClient(api_key=os.environ["BAND_USER_API_KEY"],
                        base_url=os.environ.get("BAND_REST_URL", "https://app.band.ai").rstrip("/"))
    seats = load_seats()
    room = client.human_api_chats.create_my_chat_room(chat=CreateMyChatRoomRequestChat(title=title)).data.id
    for key in seats:
        agent_id, _ = credentials(key)
        client.human_api_participants.add_my_chat_participant(room, participant=ParticipantRequest(participant_id=agent_id))
    lead_id, _ = credentials(coordinator)
    lead = seats[coordinator].name
    content = text if text.lstrip().startswith(f"@{lead}") else f"@{lead} {text}"
    client.human_api_messages.send_my_chat_message(
        room, message=ChatMessageRequest(content=content,
                                         mentions=[ChatMessageRequestMentionsItem(id=lead_id, name=lead)]))
    return room


def already_sent(record: Path | None, window_s: float = 12 * 3600) -> bool:
    import time
    return bool(record and record.is_file() and time.time() - record.stat().st_mtime < window_s)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--title", required=True)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=value")
    parser.add_argument("--print", action="store_true", help="show the rendered dispatch, send nothing")
    parser.add_argument("--save-room", type=Path, help="write the new room id here")
    parser.add_argument("--again", action="store_true",
                        help="send even though this run was dispatched in the last 12 hours (a second dispatch is a rerun)")
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env")
    values = dict(item.split("=", 1) for item in args.set)
    try:
        text = render(body_of(args.file.read_text()), values)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.print:
        print(text)
        return 0
    if already_sent(args.save_room) and not args.again:
        print(f"refusing: this run was dispatched at {args.save_room.stat().st_mtime:.0f} (room "
              f"{args.save_room.read_text().strip()}). A second dispatch is a rerun; pass --again to force.",
              file=sys.stderr)
        return 1
    room = send(text, args.title)
    if args.save_room:
        args.save_room.parent.mkdir(parents=True, exist_ok=True)
        args.save_room.write_text(room + "\n")
    print(f"room {room}: dispatch sent to the coordinator; no further human input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
