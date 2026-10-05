from factory.gates import g6_mutation
from factory.gates.g6_mutation import candidates, inside_string

from .conftest import needs_docker


def test_trailing_comments_and_docstrings_are_never_mutated(tmp_path):
    (tmp_path / "app.py").write_text(
        '"""Limits: a <= b in prose."""\n'
        'x = a + b  # noqa: A002 - silence a and b\n'
        'def f():\n    """n >= 1 here."""\n    return n >= 1\n')
    (tmp_path / "web.js").write_text('const y = a - b; // a - b and c\n')
    got = sorted((str(m.file), m.line, m.name) for m in candidates(tmp_path))
    assert got == [("app.py", 2, "plus to minus"), ("app.py", 5, "cmp >= to >"), ("web.js", 1, "minus to plus")]


def test_candidates_skip_comments_strings_and_tests(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("assert a == b\n")
    (tmp_path / "app.py").write_text('# a == b\nx = "a == b"\nif a == b and c:\n    with self.lock:\n')
    names = sorted((m.line, m.name) for m in candidates(tmp_path))
    assert names == [(3, "and to or"), (3, "eq to ne"), (4, "drop lock")]
    assert inside_string('x = "a == b"', 7) and not inside_string("a == b", 1)


@needs_docker
def test_g6_strong_tests_pass(dummy):
    folder = dummy("good")
    assert g6_mutation.main([str(folder), "--mutants", "10", "--threshold", "0.7",
                             "--health-timeout", "10"]) == 0


@needs_docker
def test_g6_weak_tests_fail(dummy):
    folder = dummy("good")
    test_file = folder / "tests" / "test_dummy.py"
    text = test_file.read_text()
    test_file.write_text(text[:text.index("def test_r2")])  # keep only one happy-path test
    assert g6_mutation.main([str(folder), "--mutants", "10", "--health-timeout", "10"]) == 1


def test_g6_gives_the_baseline_the_suite_limit_and_never_counts_a_timeout_as_a_kill(tmp_path, monkeypatch):
    """Regression: the stage-2 suite took ~250 s, gate 6 ran the unmutated baseline under the 180 s
    per-mutant limit, and every close reported 'baseline not green'. A timed-out mutant also counted as
    killed, which would have inflated the score."""
    from types import SimpleNamespace
    (tmp_path / "tests").mkdir()
    (tmp_path / "app.py").write_text("x = a + b\ny = c - d\nz = e * f\n")
    calls = []

    def fake_tested(work, gate, args, tag, extra=("-x",), timeout=None):
        calls.append((tag.rsplit("-", 1)[-1], timeout))
        if tag.endswith("-base"):
            return True
        return "timeout" if tag.endswith("-1") else False

    monkeypatch.setattr(g6_mutation, "tested", fake_tested)
    gate = SimpleNamespace(stage_dir=tmp_path, log=lambda *a: None,
                           finish=lambda passed, detail, **kw: (passed, detail, kw))
    args = SimpleNamespace(mutants=3, seed=1, threshold=0.8, min_valid=1, mutant_timeout=180,
                           suite_timeout=2400)
    passed, detail, kw = g6_mutation.check(gate, args)
    assert calls[0] == ("base", 2400)
    assert all(t >= 180 for _, t in calls[1:])
    assert "1 timed out" in detail and "killed 1/1" in detail and passed  # the timeout is not a kill
