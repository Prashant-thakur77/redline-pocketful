import subprocess

import pytest

from factory.seed_result_repo import seed


def test_seed_creates_tagged_repo_without_stage_folders(tmp_path):
    target = tmp_path / "result"
    seed(target, "Human")
    assert (target / "mandates" / "verifier.md").is_file() and (target / "factory" / "gates" / "run.py").is_file()
    assert not list(target.glob("stage-*"))
    tags = subprocess.run(["git", "-C", target, "tag"], capture_output=True, text=True).stdout.split()
    assert tags == ["factory-seed"]
    log = subprocess.run(["git", "-C", target, "log", "--format=%an"], capture_output=True, text=True).stdout.split()
    assert log == ["Human"]


def test_seed_refuses_relative_or_nonempty(tmp_path):
    with pytest.raises(ValueError):
        seed(tmp_path.relative_to(tmp_path.parent), "Human")
    (tmp_path / "x").write_text("x")
    with pytest.raises(FileExistsError):
        seed(tmp_path, "Human")
