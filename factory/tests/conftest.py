import shutil
import subprocess
from pathlib import Path

import pytest

DUMMY = Path(__file__).parent / "dummy"
collect_ignore_glob = ["dummy/*"]


def docker_ok() -> bool:
    return shutil.which("docker") is not None and subprocess.run(
        ["docker", "info"], capture_output=True).returncode == 0


needs_docker = pytest.mark.skipif(not docker_ok(), reason="Docker daemon not available")


@pytest.fixture
def dummy(tmp_path):
    """A git repo holding `stage-1/` = the dummy service in a chosen MODE."""
    def make(mode="good", name="stage-1"):
        folder = tmp_path / name
        shutil.copytree(DUMMY, folder, ignore=shutil.ignore_patterns("__pycache__"))
        dockerfile = folder / "Dockerfile"
        dockerfile.write_text(dockerfile.read_text().replace("ARG MODE=good", f"ARG MODE={mode}"))
        if not (tmp_path / ".git").exists():
            subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t",
                        "commit", "-qm", f"add {name}"], check=True)
        return folder
    return make
