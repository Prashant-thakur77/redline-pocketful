import json

import httpx

from factory import export_room, ingest
from factory.band import BandAgent
from factory.ledger import Ledger
from factory.metrics import rejections

IDS = {"planner": "p1", "builder": "b1", "verifier": "v1"}


def ev(verdict, node="n1", tokens=0):
    return ("```json\n" + json.dumps({"req": ["R-1-001"], "commit": "abcdef12", "ran": "gates", "node": node,
            "result": {"exit": 0, "passed": 3, "failed": 0}, "log": "x.log",
            "cost": {"tokens": tokens, "usd": 0, "seconds": 0}, "verdict": verdict}) + "\n```")


def msg(i, sender, to, text):
    return {"id": f"m{i}", "senderId": IDS[sender], "senderName": sender.title(), "senderType": "Agent",
            "messageType": "text", "content": f"@[[{IDS[to]}]] {text}", "insertedAt": f"2026-10-04T10:0{i}:00Z"}


def room(tmp_path):
    path = tmp_path / "room.json"
    path.write_text(json.dumps({"scope": "full", "messages": [
        msg(1, "planner", "builder", "build n1"),
        msg(2, "builder", "verifier", "ready " + ev("READY", tokens=500)),
        msg(3, "verifier", "builder", "storm broke " + ev("NEEDS_WORK")),
        msg(4, "builder", "verifier", "fixed " + ev("READY")),
        msg(5, "verifier", "planner", "all green " + ev("GO")),
    ]}))
    return path


def test_ingest_builds_rejection_ledger_and_is_idempotent(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    assert ingest.ingest(room(tmp_path), ledger) == 7  # 4 handoffs, 2 verdicts, 1 cost
    assert ingest.ingest(room(tmp_path), ledger) == 0
    [row] = rejections(ledger.events())
    assert row["verdict"] == "NEEDS_WORK" and row["to"] == ["builder"] and row["recovered_by"] == "room:m5"
    assert ledger.verify()[0]


def test_seat_recorded_verdict_not_double_counted(tmp_path):
    from factory import record
    evidence = tmp_path / "ev"
    record.main(["verdict", "--stage", "1", "--node", "n1", "--verdict", "NEEDS_WORK", "--evidence", str(evidence)])
    ledger = Ledger(evidence / "ledger.jsonl")
    ingest.ingest(room(tmp_path), ledger)
    assert len(rejections(ledger.events())) == 1


def test_export_redacts_and_follows_pages(tmp_path):
    pages = {None: ([{"id": "1", "content": "key " + "sk-" + "a" * 22, "sender_type": "Agent"}], "c"),
             "c": ([{"id": "2", "content": "ANTHROPIC_API_KEY=abc123 ok", "sender_type": "Agent"}], None)}

    def handler(request):
        data, nxt = pages[request.url.params.get("cursor")]
        return httpx.Response(200, json={"data": data, "metadata": {"next_cursor": nxt, "has_more": bool(nxt)}})

    agent = BandAgent("planner", "p1", "k", rest_url="https://band.test", transport=httpx.MockTransport(handler))
    out = export_room.to_console(agent.context("room"))
    text = json.dumps(out)
    assert len(out["messages"]) == 2 and "sk-abc" not in text and "abc123" not in text
    assert "ANTHROPIC_API_KEY=[REDACTED]" in text


def test_export_refuses_to_write_room_json(tmp_path):
    import pytest
    with pytest.raises(SystemExit):
        export_room.main(["--room", "r", "--out", str(tmp_path / "room.json")])


def test_room_events_ingested_late_still_count_as_recovered(tmp_path):
    from factory.events import Event
    path = tmp_path / "room.json"
    path.write_text(json.dumps({"messages": [msg(3, "verifier", "builder", "storm broke " + ev("NEEDS_WORK"))]}))
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ledger.append(Event(kind="verdict", stage=1, node="n1", seat="verifier", source="seat:verifier",
                        ts="2026-10-04T10:09:00+00:00", payload={"verdict": "GO"}))
    ingest.ingest(path, ledger)   # the 10:03 NEEDS_WORK lands after the 10:09 GO in the file
    [row] = rejections(ledger.events())
    assert row["recovered_by"] == "seat:verifier"
    assert "@[[" not in row["what"]


def test_measured_usage_and_log_spend_become_cost_events(tmp_path):
    from factory.events import Event
    from factory.metrics import cost_by_seat, with_inferred_stages
    path = tmp_path / "room.json"
    usage = {"id": "u1", "senderId": "b1", "senderName": "Builder", "senderType": "Agent", "messageType": "task",
             "content": "Token usage", "insertedAt": "2026-10-04T10:02:00",  # naive: treated as UTC
             "metadata": {"band_usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_tokens": 1000}}}
    path.write_text(json.dumps({"messages": [msg(1, "planner", "builder", "go"), usage]}))
    ledger = Ledger(tmp_path / "l.jsonl")
    ingest.ingest(path, ledger)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "builder.log").write_text(
        "2026-10-04 15:32:00,123 INFO band.adapters.claude_sdk: Room ROOM1: Complete - 4200ms, $0.3100\n"
        "2026-10-04 15:33:00,000 INFO band.adapters.claude_sdk: Room OTHER: Complete - 10ms, $9.0000\n")
    assert ingest.ingest_logs(logs, "ROOM1", ledger) == 1
    assert ingest.ingest_logs(logs, "ROOM1", ledger) == 0  # idempotent
    ledger.append(Event(kind="handoff", stage=1, node="n1", source="seat:planner", ts="2026-10-04T09:00:00+00:00",
                        payload={"to": ["builder"]}))
    events = with_inferred_stages(ledger.events())
    builder = cost_by_seat([e for e in events if e.stage == 1])["builder"]
    assert builder["tokens"].value == 1150 and builder["usd"].value == 0.31 and builder["seconds"].value == 4.2


def test_gzipped_room_log_loads(tmp_path):
    import gzip
    from factory import roomlog
    path = room(tmp_path)
    gz = tmp_path / "room.json.gz"
    gz.write_bytes(gzip.compress(path.read_bytes()))
    assert len(roomlog.load(gz)) == len(roomlog.load(path)) == 5


def test_a_rejection_counts_as_recovered_when_its_item_or_fix_item_later_holds():
    """Regression: the official run closed items on HOLDS (GO waits for the stage close) and fixed
    breaches under their own ids (N2-4B for N2-4), so the report called every rejection unrecovered."""
    from factory.events import Event

    def v(node, verdict, minute, seat="verifier"):
        return Event(kind="verdict", stage=2, node=node, seat=seat, source=f"seat:{seat}:{minute}",
                     ts=f"2026-10-05T03:{minute:02d}:00+00:00", payload={"verdict": verdict})

    rows = rejections([v("N2-4A", "BREACH", 1, "adversary"), v("N2-4B", "HOLDS", 9),
                       v("N2-5", "NEEDS_WORK", 2), v("N2-5", "HOLDS", 8),
                       v("N2-7'", "NEEDS_WORK", 3), v("N2-8", "HOLDS", 7)])
    got = {r["node"]: r["recovered_by"] for r in rows}
    assert got == {"N2-4A": "seat:verifier:9", "N2-5": "seat:verifier:8", "N2-7'": None}  # N2-8 is another item


def test_log_spend_is_the_difference_between_running_totals(tmp_path):
    """Regression: the seat log prints the session's running total after each turn; the official
    run's report summed those totals and showed ~$27,000 where ~$370 was spent."""
    logs = tmp_path / "logs"
    logs.mkdir()
    line = "2026-10-04 15:3{}:00,000 INFO band.adapters.claude_sdk: Room R1: Complete - 1000ms, ${}\n"
    (logs / "planner.log").write_text(line.format(1, "2.0000") + line.format(2, "5.5000")
                                      + line.format(3, "1.2500"))  # a restart begins a new running total
    ledger = Ledger(tmp_path / "l.jsonl")
    assert ingest.ingest_logs(logs, "R1", ledger) == 3
    assert [e.payload["usd"] for e in ledger.events()] == [2.0, 3.5, 1.25]
