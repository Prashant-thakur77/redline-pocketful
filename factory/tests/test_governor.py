from datetime import datetime, timedelta, timezone

from factory import governor, record
from factory.events import Event
from factory.gates import g8_budget
from factory.ledger import Ledger

CAPS = {"node": {"attempts": 2, "minutes": 30, "tokens": 1000, "usd": 1}, "stage": {"usd": 5, "minutes": 600}}
T0 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


def ev(kind, minutes=0, node="n1", **payload):
    return Event(kind=kind, stage=1, node=node, source="t", ts=(T0 + timedelta(minutes=minutes)).isoformat(),
                 payload=payload)


def test_within_caps():
    events = [ev("handoff"), ev("verdict", 5, verdict="NEEDS_WORK"), ev("cost", 6, tokens=10, usd=0.1)]
    assert governor.trips(events, 1, "n1", CAPS, now=T0 + timedelta(minutes=10)) == []


def test_attempts_time_tokens_and_stage_spend_trip():
    events = [ev("handoff"), *[ev("verdict", i, verdict="BREACH") for i in range(3)],
              ev("cost", 1, tokens=5000, usd=6)]
    found = governor.trips(events, 1, "n1", CAPS, now=T0 + timedelta(minutes=45))
    text = " ".join(found)
    assert "attempts" in text and "minutes" in text and "tokens" in text and "stage: usd" in text


def test_other_nodes_do_not_count():
    events = [*[ev("verdict", i, node="n2", verdict="BLOCK") for i in range(5)], ev("handoff")]
    assert governor.trips(events, 1, "n1", CAPS, now=T0) == []


def test_record_and_gate8_end_to_end(tmp_path):
    evidence = tmp_path / "evidence"
    (tmp_path / "stage-1").mkdir()
    record.main(["dispatch", "--stage", "1", "--node", "n1", "--to", "builder", "--evidence", str(evidence)])
    assert g8_budget.main([str(tmp_path / "stage-1"), "--node", "n1", "--evidence", str(evidence)]) == 0
    for _ in range(5):
        record.main(["verdict", "--stage", "1", "--node", "n1", "--verdict", "NEEDS_WORK",
                     "--text", "gate 2 red", "--evidence", str(evidence)])
    assert g8_budget.main([str(tmp_path / "stage-1"), "--node", "n1", "--evidence", str(evidence)]) == 1
    ledger = Ledger(evidence / "ledger.jsonl")
    assert ledger.verify()[0]
    assert ledger.events()[-1].payload["trips"]


def test_go_is_refused_while_a_gate_is_red(tmp_path):
    from factory.events import Event
    evidence = tmp_path / "evidence"
    ledger = Ledger(evidence / "ledger.jsonl")
    for gate, passed in (("g1", True), ("g2", False), ("g4", True)):
        ledger.append(Event(kind="gate_result", stage=1, node="n1", source=f"gate:{gate}",
                            payload={"gate": gate, "passed": passed, "commit": "abc1234def"}))
    go = ["verdict", "--stage", "1", "--node", "n1", "--verdict", "GO", "--commit", "abc1234", "--evidence", str(evidence)]
    assert record.main(go) == 1
    ledger.append(Event(kind="gate_result", stage=1, node="n1", source="gate:g2b",
                        payload={"gate": "g2", "passed": True, "commit": "abc1234def"}))
    assert record.main(go) == 0
    assert record.main(["verdict", "--stage", "1", "--node", "n2", "--verdict", "GO", "--commit", "abc1234",
                        "--evidence", str(evidence)]) == 1  # no gate results at all for n2
