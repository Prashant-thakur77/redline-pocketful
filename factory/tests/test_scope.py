import subprocess

from factory.scope import violations


def commit(repo, author, files=None, delete=None, msg="work", committer=None):
    for path, text in (files or {}).items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
    for path in delete or []:
        (repo / path).unlink()
    subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
    subprocess.run(["git", "-C", repo, "-c", f"user.name={committer or author}", "-c", "user.email=x@band.local",
                    "commit", "-qm", msg, f"--author={author} <x@band.local>"], check=True)
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()


def repo(tmp_path):
    subprocess.run(["git", "init", "-q", tmp_path], check=True)
    return commit(tmp_path, "Planner", {"plan/s.md": "x"}, msg="seed")


def test_seats_inside_scope_pass(tmp_path):
    base = repo(tmp_path)
    commit(tmp_path, "Redline", {"stage-1/tests/test_a.py": "t"})
    commit(tmp_path, "Builder", {"stage-1/app.py": "a", "stage-1/tests/repro/test_b.py": "r"})
    commit(tmp_path, "Adversary", {"stage-1/tests/adversarial/test_c.py": "c"})
    commit(tmp_path, "Verifier", {"evidence/gates/x.log": "log"})
    commit(tmp_path, "Builder", {"plan/lessons.md": "- rule"})
    assert violations(tmp_path, f"{base}..HEAD") == []


def test_out_of_scope_edits_and_strangers_flagged(tmp_path):
    base = repo(tmp_path)
    commit(tmp_path, "Builder", {"stage-1/tests/test_a.py": "weakened"})
    commit(tmp_path, "Verifier", {"stage-1/app.py": "healed"})
    commit(tmp_path, "Prashant", {"stage-1/app.py": "hand-written"})
    found = violations(tmp_path, f"{base}..HEAD")
    assert len(found) == 3
    assert "builder edited stage-1/tests/test_a.py" in found[2]
    assert "not a seat" in found[0]


def test_copy_forward_allowed_but_changed_copy_is_not(tmp_path):
    base = repo(tmp_path)
    commit(tmp_path, "Redline", {"stage-1/tests/test_a.py": "t"})
    commit(tmp_path, "Builder", {"stage-1/app.py": "a"})
    commit(tmp_path, "Builder", {"stage-2/tests/test_a.py": "t", "stage-2/app.py": "a"}, msg="copy forward")
    assert violations(tmp_path, f"{base}..HEAD") == []
    commit(tmp_path, "Builder", {"stage-3/tests/test_a.py": "changed"})
    assert len(violations(tmp_path, f"{base}..HEAD")) == 1


def test_deleted_test_reported_even_for_owner(tmp_path):
    base = repo(tmp_path)
    commit(tmp_path, "Redline", {"stage-1/tests/test_a.py": "t"})
    commit(tmp_path, "Redline", delete=["stage-1/tests/test_a.py"])
    assert "deleted test" in violations(tmp_path, f"{base}..HEAD")[0]


def test_owner_restore_clears_violation(tmp_path):
    base = repo(tmp_path)
    commit(tmp_path, "Redline", {"stage-1/tests/test_a.py": "strict"})
    mid = commit(tmp_path, "Builder", {"stage-1/app.py": "a"})
    commit(tmp_path, "Builder", {"stage-1/tests/test_a.py": "weak"})
    assert len(violations(tmp_path, f"{mid}..HEAD")) == 1
    commit(tmp_path, "Redline", {"stage-1/tests/test_a.py": "strict"})
    assert violations(tmp_path, f"{mid}..HEAD") == []
    assert violations(tmp_path, f"{base}..HEAD") == []


def test_commit_under_another_seats_name_is_flagged(tmp_path):
    base = repo(tmp_path)
    commit(tmp_path, "Redline", {"stage-1/tests/test_a.py": "t"}, committer="Planner")
    commit(tmp_path, "Builder", {"stage-1/app.py": "a"}, committer="Prashant")
    found = violations(tmp_path, f"{base}..HEAD")
    assert len(found) == 2 and "committed by 'Planner' under 'Redline'" in found[1]
