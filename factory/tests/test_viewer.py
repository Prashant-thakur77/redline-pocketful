from factory import ingest, metrics, roomlog, viewer
from factory.ledger import Ledger

from .test_room import room


def test_viewer_replays_room_counts_autonomy_and_escapes(tmp_path):
    path = room(tmp_path)
    ledger = Ledger(tmp_path / "l.jsonl")
    ingest.ingest(path, ledger)
    page = viewer.render(roomlog.load(path), metrics.chronological(ledger.events()), None, "Toy <run>")
    assert "Toy &lt;run&gt;" in page and "<run>" not in page
    assert page.count('class="msg"') == 5
    assert "NEEDS_WORK" in page and "@[[" not in page
    assert '<div class="kpi"><b>0</b><span>human messages after the dispatch</span>' in page
    assert "viewport" in page
