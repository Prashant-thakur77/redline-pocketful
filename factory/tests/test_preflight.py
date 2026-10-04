import httpx

from factory import preflight
from factory.seats import load_seats

SEATS = list(load_seats())


def env_for(seats, ids=None):
    env = {"BAND_REST_URL": "https://band.test"}
    for i, seat in enumerate(seats):
        env[f"BAND_AGENT_ID_{seat.upper()}"] = (ids or {}).get(seat, f"id-{seat}")
        env[f"BAND_API_KEY_{seat.upper()}"] = f"key-{seat}"
    return env


def band(owner_of=lambda key: "owner-1"):
    def handler(request):
        seat = request.headers["X-API-Key"].removeprefix("key-")
        return httpx.Response(200, json={"data": {"id": f"id-{seat}", "handle": f"acct/{seat}",
                                                  "owner_uuid": owner_of(seat)}})
    return httpx.MockTransport(handler)


def test_five_distinct_seats_one_account_is_green():
    report = preflight.Report()
    preflight.check_seats(report, env_for(SEATS), transport=band())
    assert {s for s, _, _ in report.rows} == {"OK"}
    assert report.rows[-1][1] == "distinct seats"


def test_missing_credentials_are_todo_not_ok():
    report = preflight.Report()
    preflight.check_seats(report, env_for(SEATS[:3]), transport=band())
    assert sum(1 for s, _, _ in report.rows if s == "TODO") == 2
    assert report.code(allow_todo=False) == 1 and report.code(allow_todo=True) == 0


def test_two_accounts_fail():
    report = preflight.Report()
    preflight.check_seats(report, env_for(SEATS), transport=band(lambda s: "o2" if s == "verifier" else "o1"))
    assert any(s == "FAIL" and label == "one BAND account" for s, label, _ in report.rows)


def test_mandate_header_mismatch_and_track_word_fail(tmp_path):
    seats = load_seats()
    for key, seat in seats.items():
        (tmp_path / f"{key}.md").write_text(f"Harness: {seat.harness}\nModel: {seat.model}\n\nGeneric rules.\n")
    (tmp_path / "builder.md").write_text("Harness: Codex\nModel: x\n")
    words = tmp_path / "words.txt"
    words.write_text("gizmo\n")
    (tmp_path / "planner.md").write_text(
        f"Harness: {seats['planner'].harness}\nModel: {seats['planner'].model}\nPlan the gizmo.\n")
    report = preflight.Report()
    preflight.check_mandates(report, tmp_path, None, words)
    failed = {label for s, label, _ in report.rows if s == "FAIL"}
    assert failed == {"mandate builder", "mandates track-free"}


def test_readiness_table_is_dated_and_marks_status(tmp_path):
    report = preflight.Report()
    report.add("OK", "seat planner", "acct/planner")
    report.add("FAIL", "Docker daemon", "not running")
    preflight.write_readiness(report, tmp_path / "r.md", 1)
    text = (tmp_path / "r.md").read_text()
    assert "verified live" in text and "NOT READY" in text and "| Docker daemon | ❌ |" in text
