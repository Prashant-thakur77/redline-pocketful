import pytest

from factory.gates import g7_ui
from factory.ledger import Ledger

from .conftest import needs_docker

pytest.importorskip("playwright")
pytestmark = needs_docker


def test_states_regex():
    html = '<p data-state="empty"></p><div data-state=loading>'
    js = 'el.dataset.state = "error"; h("div", {"data-state": "empty"})'
    assert g7_ui.states_in(html + js, "http://x") == {"empty", "loading", "error"}


def test_g7_passes_clean_page(dummy):
    folder = dummy("good")
    assert g7_ui.main([str(folder)]) == 0
    shots = list((folder.parent / "evidence" / "ui" / "s1").glob("*.png"))
    assert len(shots) == 3


def test_g7_fails_overflow_and_unlabelled_input(dummy):
    folder = dummy("wideui")
    assert g7_ui.main([str(folder)]) == 1
    detail = Ledger(folder.parent / "evidence" / "ledger.jsonl").events()[-1].payload["detail"]
    assert "horizontal overflow" in detail and "axe" in detail
