from pathlib import Path

from factory.genericity import files_under, scan, scan_text

VOCAB = {"/payments", "to_handle", "insufficient_funds", "pay-submit"}
WORDS = {"wallet", "booking"}


def test_flags_endpoint_field_code_noun_and_stage():
    text = "\n".join([
        "Call /payments with to_handle.",
        "Return insufficient_funds when short.",
        "Wallets must reconcile.",
        "Finish stage 2 before stage-3.",
        "Click pay-submit.",
    ])
    terms = [t for _, t in scan_text(text, VOCAB, WORDS)]
    assert "/payments" in terms and "to_handle" in terms and "insufficient_funds" in terms
    assert "wallets" in terms and "stage 2" in terms and "stage-3" in terms and "pay-submit" in terms


def test_generic_prose_passes():
    text = ("Hand off to the next seat by @handle. Every handoff carries an evidence block. "
            "Reject any change that deletes a test. Stages are copied forward.")
    assert scan_text(text, VOCAB, WORDS) == []


def test_factory_and_mandates_are_track_free():
    root = Path(__file__).resolve().parents[2]
    from factory.genericity import kickoff_vocabulary, word_list
    kickoff = root.parent / "dark-factory-wearedevs"
    vocab = kickoff_vocabulary(kickoff) if kickoff.is_dir() else set()
    files = files_under(root / "factory", root / "mandates")
    files = [f for f in files if "tests" not in f.parts]
    assert scan(files, vocab, word_list(root / "plan" / "track-words.txt")) == []


def test_python_code_identifiers_ignored_but_strings_scanned(tmp_path):
    src = tmp_path / "x.py"
    src.write_text('from collections import Counter\nparts = s.split(",")\nURL = "/payments"  # a wallet\n')
    hits = scan([src], VOCAB, WORDS)
    assert len(hits) == 2 and all(":3:" in h for h in hits)
