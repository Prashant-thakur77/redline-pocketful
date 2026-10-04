import pytest

from factory.seats import load_seats, model_for


def test_roster_has_five_distinct_seats():
    seats = load_seats()
    assert set(seats) == {"planner", "redline", "builder", "adversary", "verifier"}
    assert len({s.name for s in seats.values()}) == 5


def test_verifier_is_read_only():
    seats = load_seats()
    assert seats["verifier"].edits == []


def test_edit_scopes():
    seats = load_seats()
    assert seats["builder"].may_edit("stage-1/src/app.py")
    assert not seats["builder"].may_edit("stage-1/tests/test_a.py")
    assert seats["builder"].may_edit("stage-1/tests/repro/test_bug.py")
    assert seats["redline"].may_edit("stage-2/tests/test_a.py")
    assert not seats["redline"].may_edit("stage-2/src/app.py")
    assert not seats["redline"].may_edit("stage-2/tests/adversarial/test_x.py")
    assert seats["adversary"].may_edit("stage-1/tests/adversarial/test_x.py")
    assert not seats["adversary"].may_edit("stage-1/tests/test_x.py")
    assert not seats["verifier"].may_edit("anything")


def test_model_for_unknown_seat_fails_loudly():
    assert model_for("builder")
    with pytest.raises(KeyError):
        model_for("nobody")


def test_bad_yaml_rejected(tmp_path):
    bad = tmp_path / "seats.yaml"
    bad.write_text("seats: {}\n")
    with pytest.raises(ValueError):
        load_seats(bad)


def test_star_does_not_cross_directories():
    seats = load_seats()
    assert not seats["redline"].may_edit("stage-1/app/tests/x.py")
    assert seats["builder"].may_edit("stage-1/src/tests/x.py")  # only stage-*/tests/ is forbidden
    assert seats["builder"].may_edit("stage-1/src/app.py")
    assert not seats["builder"].may_edit("stage-1/tests/deep/x.py")
