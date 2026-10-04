import textwrap

from factory.gates import g3_public_checks


def fake_kickoff(tmp_path, claim):
    pkg = tmp_path / "kickoff" / "harness"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(textwrap.dedent(f"""
        import sys
        args = sys.argv
        print("  stage 1: pass")
        print("  stage 2: fail")
        print("claimed stage: {claim}")
        sys.exit(0)
    """))
    return tmp_path / "kickoff"


def test_g3_passes_when_stage_claimed(tmp_path):
    (tmp_path / "repo" / "stage-1").mkdir(parents=True)
    kickoff = fake_kickoff(tmp_path, "1")
    assert g3_public_checks.main([str(tmp_path / "repo" / "stage-1"), "--track", "any",
                                  "--kickoff", str(kickoff)]) == 0


def test_g3_fails_when_not_claimed(tmp_path):
    (tmp_path / "repo" / "stage-1").mkdir(parents=True)
    kickoff = fake_kickoff(tmp_path, "none")
    assert g3_public_checks.main([str(tmp_path / "repo" / "stage-1"), "--track", "any",
                                  "--kickoff", str(kickoff)]) == 1
