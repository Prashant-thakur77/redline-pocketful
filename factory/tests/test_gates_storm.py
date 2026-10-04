import shutil

from factory.gates import g4_storm, g5_regression
from factory.ledger import Ledger

from .conftest import needs_docker

pytestmark = needs_docker


def test_g4_holds_on_good_service(dummy):
    assert g4_storm.main([str(dummy("good")), "--ops", "1000"]) == 0


def test_g4_catches_lost_updates(dummy):
    folder = dummy("racy")
    assert g4_storm.main([str(folder), "--ops", "400"]) == 1
    detail = Ledger(folder.parent / "evidence" / "ledger.jsonl").events()[-1].payload["detail"]
    assert "invariant broken" in detail


def test_g4_fails_without_hook(dummy):
    folder = dummy("good")
    shutil.rmtree(folder / "tests" / "invariants")
    assert g4_storm.main([str(folder), "--ops", "10"]) == 1


def test_g5_passes_when_earlier_tests_hold(dummy):
    dummy("good", name="stage-1")
    assert g5_regression.main([str(dummy("good", name="stage-2"))]) == 0


def test_g5_catches_regression(dummy):
    dummy("good", name="stage-1")
    assert g5_regression.main([str(dummy("racy", name="stage-2"))]) == 1


def test_g5_first_stage_has_nothing_to_regress(dummy):
    assert g5_regression.main([str(dummy("good"))]) == 0


def test_g2_misses_but_g4_catches_concurrent_retry_bug(dummy):
    from factory.gates import g2_spec_tests
    folder = dummy("dupe")
    assert g2_spec_tests.main([str(folder)]) == 0
    assert g4_storm.main([str(folder), "--ops", "600", "--replay", "0.5"]) == 1
