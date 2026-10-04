from factory import ingest, report
from factory.events import Event
from factory.ledger import Ledger

from .test_room import room


def seeded(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    ingest.ingest(room(tmp_path), ledger)
    for gate, payload in [("g2", {"counts": {"passed": 40, "tests": 40}}), ("g6", {"score": 0.86}),
                          ("g4", {"ops": 1300})]:
        ledger.append(Event(kind="gate_result", stage=1, node="close", source=f"gate:{gate}",
                            payload={"gate": gate, "passed": True, **payload}))
    ledger.append(Event(kind="cost", seat="builder", stage=1, source="seat:builder",
                        payload={"tokens": 1000, "usd": 1.25, "seconds": 600}))
    ledger.append(Event(kind="stage_closed", seat="planner", stage=1, source="seat:planner",
                        payload={"result": "closed"}))
    return ledger


def test_report_tables(tmp_path):
    ledger = seeded(tmp_path)
    body = report.build(ledger.events(), ledger.verify(), tmp_path / "room.json", None)
    assert "| 1 | closed | ✅ 40/40 | ✅ 1300 ops | ✅ 86% killed |" in body
    assert "NEEDS_WORK" in body and "`room:m3`" in body
    assert "$1.25" in body and "hash chain intact" in body
    assert "both directions" in body


def test_inject_and_summary(tmp_path):
    ledger = seeded(tmp_path)
    factory_md = tmp_path / "FACTORY.md"
    factory_md.write_text(f"# F\n\n{report.START}\nold\n{report.END}\n\nafter\n")
    assert report.main(["--ledger", str(ledger.path), "--room", str(tmp_path / "room.json"),
                        "--out", str(tmp_path / "r.md"), "--dossier", str(tmp_path / "d"),
                        "--inject", str(factory_md)]) == 0
    text = factory_md.read_text()
    assert "old" not in text and "after" in text and "Results per stage" in text
    assert (tmp_path / "d" / "stage-1.html").is_file()
    assert "stage 1: closed" in report.summary(ledger.events())


def test_rejection_row_shows_the_change_it_forced(tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    def commit(text):
        (repo / "app.py").write_text(text)
        subprocess.run(["git", "-C", repo, "add", "."], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=b", "-c", "user.email=b@x", "commit", "-qm", "x"], check=True)
        return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    subprocess.run(["git", "init", "-q", repo], check=True)
    bad, good = commit("a\n"), commit("a\nlock\nfix\n")
    ledger = Ledger(tmp_path / "l.jsonl")
    ledger.append(Event(kind="verdict", stage=1, node="n1", seat="verifier", source="room:m1",
                        payload={"verdict": "NEEDS_WORK", "text": "storm broke", "commit": bad}))
    ledger.append(Event(kind="verdict", stage=1, node="n1", seat="verifier", source="room:m2",
                        payload={"verdict": "GO", "commit": good}))
    [row] = report.rejection_rows(ledger.events(), repo)[2:]
    assert f"{bad[:7]}→{good[:7]}" in row and "2 +" in row


def test_measured_costs_replace_estimates_and_get_the_working_stage(tmp_path):
    from factory import metrics
    events = [Event(kind="handoff", stage=2, node="n1", source="room:a", ts="2026-10-04T10:00:00+00:00"),
              Event(kind="cost", seat="builder", stage=2, source="room:b", ts="2026-10-04T10:01:00+00:00",
                    payload={"tokens": 9, "usd": 99, "seconds": 9999, "estimate": True}),
              Event(kind="cost", seat="builder", source="log:builder:7", ts="2026-10-04T10:02:00+00:00",
                    payload={"usd": 1.5, "seconds": 30})]
    out = metrics.measured_only(metrics.with_inferred_stages(events))
    costs = [e for e in out if e.kind == "cost"]
    assert len(costs) == 1 and costs[0].stage == 2 and costs[0].payload["usd"] == 1.5
