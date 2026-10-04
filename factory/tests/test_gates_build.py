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
