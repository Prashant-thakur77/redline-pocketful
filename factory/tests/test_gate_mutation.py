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
