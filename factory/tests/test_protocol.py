import pytest

from factory.protocol import Evidence, EvidenceError, format_handoff, parse_evidence, try_parse

GOOD = {"req": ["R-1", "R-2"], "commit": "9f3c2e1", "ran": "pytest -q",
        "result": {"exit": 0, "passed": 12, "failed": 0}, "log": "evidence/x.log",
        "cost": {"tokens": 4100, "usd": 0.06, "seconds": 37}, "verdict": "GO"}


def test_round_trip():
    ev = Evidence.model_validate(GOOD)
    msg = format_handoff("all gates green", ev, ["planner", "@builder"])
    assert msg.startswith("@planner @builder all gates green")
    assert parse_evidence(msg) == ev


def test_picks_first_valid_block_among_several():
    msg = "```json\n{\"note\": 1}\n```\nthen\n```json\n" + Evidence.model_validate(GOOD).model_dump_json() + "\n```"
    assert parse_evidence(msg).verdict == "GO"


@pytest.mark.parametrize("field,value", [("verdict", "LGTM"), ("req", []), ("commit", "abc")])
def test_invalid_fields_rejected(field, value):
    bad = {**GOOD, field: value}
    with pytest.raises(EvidenceError):
        parse_evidence(f"```json\n{__import__('json').dumps(bad)}\n```")


def test_missing_block():
    assert try_parse("looks good to me @verifier") is None


def test_unaddressed_handoff_refused():
    with pytest.raises(EvidenceError):
        format_handoff("done", Evidence.model_validate(GOOD), [])
