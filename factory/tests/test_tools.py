import json
import subprocess

import pytest

from factory import lessons, stage_copy
from factory.gates import run as gate_run

from .conftest import needs_docker


def test_lessons_add_dedupes(tmp_path):
    path = tmp_path / "plan" / "lessons.md"
    assert lessons.add(path, "builder", "retry applied twice", "key every write by its request id")
    assert not lessons.add(path, "verifier", "same again", "key every write by its request id")
    assert path.read_text().count("→") == 1


def test_stage_copy_skips_git_and_refuses_overwrite(tmp_path):
    src = tmp_path / "stage-1"
    (src / ".git").mkdir(parents=True)
    (src / "app.py").write_text("x")
    (src / "__pycache__").mkdir()
    assert stage_copy.copy_forward(src, tmp_path / "stage-2") == 1
    assert not (tmp_path / "stage-2" / ".git").exists()
    with pytest.raises(FileExistsError):
        stage_copy.copy_forward(src, tmp_path / "stage-2")


@needs_docker
def test_run_shares_service_and_reports(dummy, capsys):
    folder = dummy("good")
    base = subprocess.run(["git", "-C", folder.parent, "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()
    assert gate_run.main([str(folder), "--node", "n1", "--gates", "1,2,4,8"]) == 0
    out = capsys.readouterr().out
    summary = json.loads(out[out.index("{\n"):])
    assert summary["gates"] == {"g1": "pass", "g2": "pass", "g4": "pass", "g8": "pass"}
    assert summary["result"]["passed"] == 5
    # an out-of-scope commit by an unknown author fails the scope check
    (folder / "app.py").write_text((folder / "app.py").read_text() + "\n# hand edit\n")
    subprocess.run(["git", "-C", folder.parent, "-c", "user.name=Someone", "-c", "user.email=s@x",
                    "commit", "-qam", "hand edit"], check=True)
    assert gate_run.main([str(folder), "--node", "n1", "--gates", "8", "--scope", f"{base}..HEAD"]) == 1


@needs_docker
def test_run_stops_service_gates_when_build_fails(dummy):
    folder = dummy("netcall")
    assert gate_run.main([str(folder), "--gates", "1,2", "--node", "n2"]) == 1


@needs_docker
def test_run_checks_a_named_commit_in_a_private_worktree(dummy):
    folder = dummy("good")
    repo = folder.parent
    good = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dockerfile = folder / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text().replace("MODE=good", "MODE=racy"))
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "racy"], check=True)
    head = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert gate_run.main([str(folder), "--node", "w", "--gates", "2", "--commit", good]) == 0
    assert gate_run.main([str(folder), "--node", "w", "--gates", "2"]) == 1
    after = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    assert after == head  # the shared tree never moved
    assert "redline-wt" not in subprocess.run(["git", "-C", repo, "worktree", "list"], capture_output=True,
                                             text=True).stdout


def test_run_fails_a_requested_gate_it_cannot_run(dummy, capsys):
    folder = dummy("good")
    assert gate_run.main([str(folder), "--gates", "3", "--node", "x"]) == 1


@needs_docker
def test_regression_gate_gets_a_fresh_service_after_the_storm(dummy):
    first = dummy("good", name="stage-1")
    (first / "tests" / "test_00_fresh.py").write_text(
        "import os, httpx\n\n"
        "def test_fresh_service_starts_at_zero():\n"
        "    assert httpx.get(os.environ['BASE_URL'] + '/value').json()['value'] == 0\n")
    subprocess.run(["git", "-C", first.parent, "add", "."], check=True)
    subprocess.run(["git", "-C", first.parent, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fresh"],
                   check=True)
    second = dummy("good", name="stage-2")
    assert gate_run.main([str(second), "--gates", "4,5", "--node", "f"]) == 0


def test_a_timed_out_command_logs_text_not_bytes(tmp_path):
    import argparse
    from factory.gates.common import Gate, run
    (tmp_path / "stage-1").mkdir()
    gate = Gate("gx", argparse.Namespace(stage_dir=tmp_path / "stage-1", stage=1, node="t", evidence=tmp_path / "ev"))
    proc = run(["python3", "-c", "import time,sys; print('partial', flush=True); time.sleep(5)"], timeout=1, gate=gate)
    assert proc.returncode == 124 and isinstance(proc.stdout, str)
    assert "timed out" in gate.log_path.read_text()
