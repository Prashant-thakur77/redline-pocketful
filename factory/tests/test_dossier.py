from factory import dossier, metrics
from factory.events import Event
from factory.ledger import Ledger


def seed(path):
    ledger = Ledger(path)
    add = lambda **kw: ledger.append(Event(stage=1, **kw))
    add(kind="handoff", seat="builder", node="n1", source="room:m1", payload={"to": ["verifier"]})
    add(kind="gate_result", seat="verifier", node="n1", source="gate:g4",
        payload={"gate": "g4", "passed": False, "log": "evidence/g4.log"})
    add(kind="verdict", seat="verifier", node="n1", source="room:m2",
        payload={"verdict": "NEEDS_WORK", "text": "invariant broke under retries <script>"})
    add(kind="gate_result", seat="verifier", node="n1", source="gate:g4b",
        payload={"gate": "g4", "passed": True, "log": "evidence/g4b.log"})
    add(kind="verdict", seat="verifier", node="n1", source="room:m3", payload={"verdict": "GO"})
    add(kind="verdict", seat="verifier", node="n2", source="room:m4", payload={"verdict": "GO"})
    add(kind="cost", seat="builder", source="seat:builder", payload={"tokens": 1000, "usd": 0.5, "seconds": 60})
    add(kind="stage_closed", seat="planner", source="room:m5", payload={"result": "closed"})
    return ledger


def test_metrics(tmp_path):
    events = seed(tmp_path / "l.jsonl").events()
    rows = metrics.rejections(events)
    assert rows[0]["verdict"] == "NEEDS_WORK" and rows[0]["recovered_by"] == "room:m3"
    assert metrics.catch_rate(events).value == 0.5
    gate = metrics.gate_sheet(events)["g4"]
    assert (gate["runs"], gate["failures"], gate["last"]) == (2, 1, "pass")
    assert metrics.cost_by_seat(events)["builder"]["usd"].value == 0.5


def test_dossier_renders_with_provenance_and_escapes(tmp_path):
    seed(tmp_path / "l.jsonl")
    [page] = dossier.build(tmp_path / "l.jsonl", tmp_path / "out")
    text = page.read_text()
    assert "Stage 1 dossier" in text and "room:m2" in text and "gate:g4" in text
    assert "<script>" not in text and "ledger chain intact" in text
    assert "viewport" in text
