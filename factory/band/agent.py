"""BAND REST/WebSocket wrapper for one seat.

Adapted from Freight Room's band_lib. Differences: `send()` never invents a
mention (a message without a real peer mention is an error, not a fallback), a
seat can never mention itself, and room context is read through every page.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable, Iterable

import httpx

DEFAULT_REST_URL = "https://app.band.ai/"
DEFAULT_WS_URL = "wss://app.band.ai/api/v1/socket/websocket"
PAGE_LIMIT = 100


class HandoffError(ValueError):
    """A message that BAND would drop or reject: no peer mention, or a self-mention."""


class InterceptingAdapter:
    """Wraps a band-sdk adapter so a callback sees every room event first."""

    def __init__(self, target, callback: Callable):
        self.target = target
        self.callback = callback

    def __getattr__(self, name):
        return getattr(self.target, name)

    async def on_event(self, event):
        try:
            result = self.callback(event)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # an observer must never break the seat
            print(f"[intercept] callback failed: {exc}")
        return await self.target.on_event(event)


class BandAgent:
    def __init__(self, seat: str, agent_id: str, api_key: str, *,
                 rest_url: str | None = None, ws_url: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        if not agent_id or not api_key:
            raise ValueError(f"seat {seat!r} has no agent id or API key")
        self.seat = seat
        self.agent_id = agent_id
        self.api_key = api_key
        self.rest_url = (rest_url or os.getenv("BAND_REST_URL", DEFAULT_REST_URL)).rstrip("/") + "/"
        self.ws_url = ws_url or os.getenv("BAND_WS_URL", DEFAULT_WS_URL)
        self.handlers: list[Callable] = []
        self.http = httpx.Client(base_url=self.rest_url, headers={"X-API-Key": api_key},
                                 timeout=30.0, transport=transport)

    # ---- live connection (band-sdk) ----
    async def connect(self, adapter):
        from band import Agent  # lazy: tests and offline tools never need the SDK

        wrapped = InterceptingAdapter(adapter, self._dispatch)
        self.agent = Agent.create(adapter=wrapped, agent_id=self.agent_id, api_key=self.api_key,
                                  ws_url=self.ws_url, rest_url=self.rest_url)
        await self.agent.start()

    async def _dispatch(self, event):
        for handler in self.handlers:
            result = handler(event)
            if inspect.isawaitable(result):
                await result

    def on_event(self, handler: Callable):
        self.handlers.append(handler)

    # ---- REST ----
    def me(self) -> dict:
        return self._ok(self.http.get("api/v1/agent/me"))["data"]

    def create_room(self, title: str | None = None) -> str:
        body = {"chat": {"title": title} if title else {}}
        return self._ok(self.http.post("api/v1/agent/chats", json=body))["data"]["id"]

    def add_participant(self, room_id: str, participant_id: str) -> dict:
        body = {"participant": {"participant_id": participant_id, "role": "member"}}
        return self._ok(self.http.post(f"api/v1/agent/chats/{room_id}/participants", json=body))

    def participants(self, room_id: str) -> list[dict]:
        return self._ok(self.http.get(f"api/v1/agent/chats/{room_id}/participants"))["data"]

    def send(self, room_id: str, text: str, mentions: Iterable[dict]) -> dict:
        mentions = [m for m in mentions if m]
        if not mentions:
            raise HandoffError("a message must @mention at least one other seat; "
                               "an unaddressed message is never delivered")
        if any(m.get("id") == self.agent_id for m in mentions):
            raise HandoffError(f"seat {self.seat!r} cannot mention itself; hand off to a peer")
        body = {"message": {"content": text, "mentions": mentions}}
        return self._ok(self.http.post(f"api/v1/agent/chats/{room_id}/messages", json=body))

    def context(self, room_id: str) -> list[dict]:
        """Every message in the room, oldest page first, following `next_cursor`."""
        items, cursor = [], None
        while True:
            params = {"limit": PAGE_LIMIT, **({"cursor": cursor} if cursor else {})}
            body = self._ok(self.http.get(f"api/v1/agent/chats/{room_id}/context", params=params))
            items.extend(body.get("data", []))
            meta = body.get("metadata") or body.get("meta") or {}
            cursor = meta.get("next_cursor")
            if not cursor or not meta.get("has_more", True):
                return items

    @staticmethod
    def _ok(response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"BAND {response.request.method} {response.request.url.path} -> "
                f"{response.status_code}: {response.text[:300]}",
                request=response.request, response=response)
        return response.json()

    def close(self):
        self.http.close()


async def heartbeat(agent: BandAgent, every: float = 30.0):  # pragma: no cover - long-running
    while True:
        try:
            agent.me()
        except Exception as exc:
            print(f"[{agent.seat}] heartbeat failed: {exc}")
        await asyncio.sleep(every)
