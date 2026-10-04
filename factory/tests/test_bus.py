import json

import pytest

from factory import roomlog
from factory.sim.bus import MentionError, Room


def room():
    return Room.with_seats({"planner": "Planner", "builder": "Builder", "verifier": "Verifier"})


def test_only_mentioned_seats_receive():
    r = room()
    r.post("human", "@planner build it")
    r.post("planner", "@builder item n1, email a@b.c is not a mention")
    assert [m["content"] for m in r.inbox("builder")] == ["@builder item n1, email a@b.c is not a mention"]
    assert r.inbox("verifier") == [] and len(r.inbox("planner")) == 1
    assert r.inbox("builder") == []  # read once


def test_band_rejections():
    r = room()
    with pytest.raises(MentionError):
        r.post("builder", "done, nobody addressed")
    with pytest.raises(MentionError):
        r.post("builder", "@builder @verifier ready")
    assert r.messages == []


def test_saved_room_reads_like_console_download_and_passes_harness_rule(tmp_path):
    r = room()
    r.post("human", "@planner go")
    r.post("planner", "@builder do n1")
    r.post("builder", "@planner done")
    r.save(tmp_path / "room.json")
    messages = roomlog.load(tmp_path / "room.json")
    assert messages[1].mentions == ["p-builder"] and messages[0].agent is False
    raw = json.loads((tmp_path / "room.json").read_text())
    assert "@[[p-planner]]" in raw["messages"][2]["content"]
