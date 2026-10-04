import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from factory.events import Event
from factory.ledger import GENESIS, Ledger


def ev(i=0, kind="cost"):
    return Event(kind=kind, seat="builder", stage=1, node=f"n{i}", source="seat:builder",
                 payload={"tokens": i})


def test_chain_links_and_verifies(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    first = ledger.append(ev(1))
    second = ledger.append(ev(2))
    assert first.prev == GENESIS and second.prev == first.hash
    assert ledger.verify() == (True, "ok")


def test_tampering_is_detected(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    for i in range(3):
        ledger.append(ev(i))
    lines = path.read_text().splitlines()
    edited = json.loads(lines[1])
    edited["payload"]["tokens"] = 999
    lines[1] = json.dumps(edited)
    path.write_text("\n".join(lines) + "\n")
    ok, detail = ledger.verify()
    assert not ok and "line 2" in detail


def test_deleted_line_is_detected(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    for i in range(3):
        ledger.append(ev(i))
    lines = path.read_text().splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n")
    assert not ledger.verify()[0]


def test_concurrent_appends_keep_chain(tmp_path):
    ledger = Ledger(tmp_path / "ledger.jsonl")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: ledger.append(ev(i)), range(40)))
    assert len(ledger.events()) == 40
    assert ledger.verify()[0]


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        Event(kind="chat", source="x")


def test_torn_tail_is_ignored_then_repaired(tmp_path):
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path)
    ledger.append(ev(1))
    with open(path, "a") as fh:
        fh.write('{"kind": "cost", "ts": "2026')  # writer killed mid-line
    assert len(ledger.events()) == 1
    ledger.append(ev(2))
    assert len(ledger.events()) == 2 and ledger.verify()[0]
