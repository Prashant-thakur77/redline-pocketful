"""Runtime, deployment and wire-format conventions: R-1-010..016, R-1-020..025."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import httpx

from conftest import (BASE_URL, api_get, api_post, auth, idem, login_token, make_fixture,
                       reset_ok, unique, unique_handle, user)

STAGE_DIR = Path(__file__).resolve().parent.parent


def test_dockerfile_and_run_md_present():
    """R-1-010"""
    assert (STAGE_DIR / "Dockerfile").is_file(), "Dockerfile must exist in the stage folder"
    run_md = STAGE_DIR / "RUN.md"
    assert run_md.is_file(), "RUN.md must exist in the stage folder"
    text = run_md.read_text(errors="replace")
    assert "docker build" in text and "docker run" in text, \
        "RUN.md must give the exact docker build and docker run commands"


def test_no_compose_or_sidecar_needed():
    """R-1-011"""
    for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
        assert not (STAGE_DIR / name).exists(), f"{name} must not be required to start the service"


def test_service_reachable_on_configured_port():
    """R-1-012: the service answers on the host:port given by BASE_URL (which
    tracks the PORT the service was started with, 8080 by default)."""
    r = api_get("/health")
    assert r.status_code == 200


def test_dockerfile_has_no_runtime_network_fetch():
    """R-1-013: the running container must make no outbound request; static
    check that the entrypoint/cmd does not shell out to a package manager or
    http client (such calls belong at build time, inside RUN, not at start)."""
    text = (STAGE_DIR / "Dockerfile").read_text(errors="replace")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    start_lines = [ln for ln in lines if ln.upper().startswith(("CMD", "ENTRYPOINT"))]
    assert start_lines, "Dockerfile must declare a CMD or ENTRYPOINT"
    forbidden = ("curl ", "wget ", "pip install", "npm install", "apt-get install", "apk add")
    for ln in start_lines:
        low = ln.lower()
        assert not any(f in low for f in forbidden), f"startup command fetches over the network: {ln}"


def test_no_persistent_volume_required():
    """R-1-016: service state need not survive a restart, so no volume mount
    is required to start or serve; a fresh reset is enough state."""
    text = (STAGE_DIR / "Dockerfile").read_text(errors="replace")
    assert "VOLUME" not in text.upper().replace("VOLUMES", ""), \
        "Dockerfile must not require an external volume to run"
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=500), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    r = api_get("/me", headers=auth(login_token(fixture["users"][0]["email"])))
    assert r.status_code == 200 and r.json()["balance"] == 500


def test_health_ok():
    """R-1-014"""
    r = api_get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_no_auth_required():
    """R-1-089"""
    r = api_get("/health")
    assert r.status_code == 200


def test_json_content_type_on_success():
    """R-1-020"""
    r = api_get("/health")
    assert r.headers.get("content-type", "").startswith("application/json")


def test_json_content_type_on_error():
    """R-1-020"""
    r = api_get("/me")  # unauthenticated -> 401
    assert r.status_code == 401
    assert r.headers.get("content-type", "").startswith("application/json")


def test_timestamps_are_rfc3339_with_offset():
    """R-1-021"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    created_at = r.json()["created_at"]
    # RFC 3339 with an explicit offset: must not be naive and must not bare-"Z"-less local time
    assert re.search(r"(Z|[+-]\d{2}:\d{2})$", created_at), f"timestamp missing explicit offset: {created_at}"
    # parseable
    normalized = created_at.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(normalized)
    assert parsed.tzinfo is not None


def test_unknown_request_body_fields_ignored():
    """R-1-022"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10, "unexpected_field": "surprise!"},
                 headers={**auth(token), **idem(unique("k"))})
    assert r.status_code == 201, r.text


def test_unknown_query_params_ignored():
    """R-1-023"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    r = api_get("/requests", headers=auth(token), params={"nonsense": "yes", "limit": 10})
    assert r.status_code == 200, r.text


def test_assigned_ids_are_opaque_and_bounded():
    """R-1-024"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                 headers={**auth(token), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    payment_id = r.json()["payment_id"]
    assert isinstance(payment_id, str) and 1 <= len(payment_id) <= 64


def test_seeded_ids_used_verbatim():
    """R-1-025"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    pay_id = unique("p")
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0)],
        payments=[{"id": pay_id, "from_user_id": a_id, "to_user_id": b_id, "amount": 50,
                   "note": "", "visibility": "public"}],
    )
    reset_ok(fixture)
    token = login_token(fixture["users"][0]["email"])
    r = api_get("/activity", headers=auth(token))
    assert r.status_code == 200, r.text
    ids = [p["payment_id"] for p in r.json()["payments"]]
    assert pay_id in ids
    r2 = api_get("/me", headers=auth(token))
    assert r2.status_code == 200
    assert r2.json()["user_id"] == a_id
