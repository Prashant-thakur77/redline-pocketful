from factory.gates import g1_clean_build, g2_spec_tests
from factory.ledger import Ledger

from .conftest import needs_docker

pytestmark = needs_docker


def ledger_of(folder):
    return Ledger(folder.parent / "evidence" / "ledger.jsonl")


def test_g1_passes_good_service(dummy):
    folder = dummy("good")
    assert g1_clean_build.main([str(folder), "--node", "n1"]) == 0
    [event] = ledger_of(folder).events()
    assert event.payload["gate"] == "g1" and event.payload["passed"] and event.node == "n1"
    assert (folder.parent / event.payload["log"]).is_file()


def test_g1_fails_service_that_needs_network(dummy):
    assert g1_clean_build.main([str(dummy("netcall"))]) == 1


def test_g1_fails_unhealthy_service(dummy):
    assert g1_clean_build.main([str(dummy("nohealth")), "--health-timeout", "8"]) == 1


def test_g1_fails_without_run_md(dummy):
    folder = dummy("good")
    (folder / "RUN.md").unlink()
    assert g1_clean_build.main([str(folder)]) == 1


def test_g2_passes_good_and_fails_racy(dummy):
    assert g2_spec_tests.main([str(dummy("good"))]) == 0
    assert g2_spec_tests.main([str(dummy("racy", name="stage-2"))]) == 1


def test_g2_ratchet_catches_deleted_test(dummy):
    folder = dummy("good")
    assert g2_spec_tests.main([str(folder)]) == 0
    test_file = folder / "tests" / "test_dummy.py"
    text = test_file.read_text()
    test_file.write_text(text[:text.index("def test_r4")])
    assert g2_spec_tests.main([str(folder)]) == 1
    assert "removed" in ledger_of(folder).events()[-1].payload["detail"]


def test_g2_fails_with_no_tests(dummy):
    folder = dummy("good")
    for f in (folder / "tests").glob("test_*.py"):
        f.unlink()
    assert g2_spec_tests.main([str(folder)]) == 1


def test_g2_scoped_to_an_items_requirements(dummy):
    folder = dummy("racy")  # r4 (concurrency) fails on this service, r1 passes
    assert g2_spec_tests.main([str(folder), "--req", "r1"]) == 0
    assert g2_spec_tests.main([str(folder), "--req", "r4"]) == 1
    assert g2_spec_tests.main([str(folder), "--req", "r9"]) == 1  # no test names r9: nothing proves it


def test_g2_reports_a_timed_out_suite_as_a_timeout_not_a_removed_test(tmp_path, monkeypatch):
    """Regression: a stage-2 suite ran past 900 s, pytest never wrote its report, and gate 2
    said a test had been removed (the seats had to work out it was a timeout)."""
    from types import SimpleNamespace
    (tmp_path / "tests").mkdir()
    gate = SimpleNamespace(stage_dir=tmp_path, reqs="", timeout=5.0, evidence=tmp_path,
                           finish=lambda passed, detail, **kw: (passed, detail))
    monkeypatch.setattr(g2_spec_tests, "previous_high", lambda gate: 314)
    monkeypatch.setattr(g2_spec_tests, "run_pytest", lambda *a, **kw: {
        "tests": 0, "failures": 0, "errors": 1, "skipped": 0, "exit": 124, "timed_out": True, "passed": -1})
    passed, detail = g2_spec_tests.check(gate, "http://x")
    assert not passed and "did not finish within 5s" in detail and "removed" not in detail.replace("no test was removed", "")


def test_run_pytest_flags_a_timeout(tmp_path):
    from factory.gates.common import run_pytest
    from types import SimpleNamespace
    (tmp_path / "test_slow.py").write_text("import time\n\ndef test_slow():\n    time.sleep(30)\n")
    gate = SimpleNamespace(log_path=tmp_path / "g2.log", seat=None, log=lambda *a: None)
    counts = run_pytest([tmp_path], "http://x", gate, timeout=3)
    assert counts["timed_out"] and counts["exit"] == 124
