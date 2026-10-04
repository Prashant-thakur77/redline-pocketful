"""Prove each running seat answers: a throwaway room, one tokened @mention per
seat, and a wait for a reply carrying the token. A connected seat that cannot
answer (bad model key, logged-out CLI) fails here, before any dispatch.

    python -m factory.smoke [--seats planner builder …] [--timeout 180]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

from factory.band import credentials
from factory.seats import load_seats

REPO = Path(__file__).resolve().parent.parent


def replied(messages, agent_id: str, token: str) -> bool:
    return any(m.sender_id == agent_id and m.message_type == "text" and token in (m.content or "") for m in messages)


def close_room(client, room: str):  # pragma: no cover - live BAND
    """Delete a throwaway room so restarted seats never pick up its stale messages."""
    import httpx
    wrapper = client._client_wrapper
    httpx.delete(f"{wrapper.get_base_url().rstrip('/')}/api/v1/me/chats/{room}", headers=wrapper.get_headers(),
                 timeout=30).raise_for_status()


def main(argv=None) -> int:  # pragma: no cover - live BAND
    from band_rest import ChatMessageRequest, ChatMessageRequestMentionsItem, ParticipantRequest, RestClient
    from band_rest.human_api_chats import CreateMyChatRoomRequestChat

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seats", nargs="*")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--close", nargs="*", metavar="ROOM", help="only delete these stale rooms, then exit")
    args = parser.parse_args(argv)
    load_dotenv(REPO / ".env")
    seats = load_seats()
    chosen = args.seats or list(seats)
    client = RestClient(api_key=os.environ["BAND_USER_API_KEY"],
                        base_url=os.environ.get("BAND_REST_URL", "https://app.band.ai").rstrip("/"))
    if args.close is not None:
        for stale in args.close:
            close_room(client, stale)
            print(f"closed {stale}")
        return 0
    room = client.human_api_chats.create_my_chat_room(chat=CreateMyChatRoomRequestChat(title="Redline smoke")).data.id
    pending = {}
    for key in chosen:
        agent_id, _ = credentials(key)
        client.human_api_participants.add_my_chat_participant(room, participant=ParticipantRequest(participant_id=agent_id))
        token = uuid.uuid4().hex[:10]
        name = seats[key].name
        client.human_api_messages.send_my_chat_message(room, message=ChatMessageRequest(
            content=f"@{name} smoke check: reply to me with the token {token} and nothing else.",
            mentions=[ChatMessageRequestMentionsItem(id=agent_id, name=name)]))
        pending[key] = (agent_id, token)
    deadline = time.monotonic() + args.timeout
    while pending and time.monotonic() < deadline:
        time.sleep(5)
        messages = client.human_api_messages.list_my_chat_messages(room, limit=100).data
        for key in [k for k, (aid, tok) in pending.items() if replied(messages, aid, tok)]:
            print(f"[ OK ] {key} answered")
            pending.pop(key)
    for key in pending:
        print(f"[FAIL] {key} did not answer within {args.timeout:.0f}s — check ~/.cache/redline/logs/{key}.log")
    close_room(client, room)
    return 1 if pending else 0


if __name__ == "__main__":
    sys.exit(main())
