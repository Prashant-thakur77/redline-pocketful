"""Seat identity: each seat's own credentials, resolved through `/agent/me`.

No hardcoded handles and no borrowing another seat's credentials: a seat whose
env vars are missing is a preflight failure, never a silent substitute.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from factory.band.agent import DEFAULT_REST_URL


class MissingSeat(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    seat: str
    id: str
    handle: str
    name: str
    owner: str | None


def credentials(seat: str, env: dict | None = None) -> tuple[str, str]:
    env = os.environ if env is None else env
    key = seat.upper()
    agent_id, api_key = env.get(f"BAND_AGENT_ID_{key}"), env.get(f"BAND_API_KEY_{key}")
    if not agent_id or not api_key:
        raise MissingSeat(f"seat {seat!r}: set BAND_AGENT_ID_{key} and BAND_API_KEY_{key}")
    return agent_id, api_key


def resolve(seat: str, env: dict | None = None,
            transport: httpx.BaseTransport | None = None) -> Identity:
    agent_id, api_key = credentials(seat, env)
    rest = ((env or os.environ).get("BAND_REST_URL") or DEFAULT_REST_URL).rstrip("/")
    with httpx.Client(timeout=10.0, transport=transport) as client:
        response = client.get(f"{rest}/api/v1/agent/me", headers={"X-API-Key": api_key})
    if response.status_code != 200:
        raise MissingSeat(f"seat {seat!r}: /agent/me returned HTTP {response.status_code}")
    data = response.json().get("data", {})
    if data.get("id") != agent_id:
        raise MissingSeat(f"seat {seat!r}: key belongs to agent {data.get('id')}, "
                          f"not BAND_AGENT_ID_{seat.upper()}")
    return Identity(seat=seat, id=data["id"], handle=data.get("handle", ""),
                    name=data.get("name", ""), owner=data.get("owner_uuid"))
