"""Adversarial findings against U3 (statement screen, payment detail,
refund/correct actions, operator batch table). Breach confirmed against
commit 7f94146.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import auth, make_fixture, reset_ok, tid, ui_login, unique, unique_handle, url, user  # noqa: E402

import httpx  # noqa: E402


def test_refund_correct_batch_are_dead_on_any_non_localhost_origin_r_u_036_037_039(page):
    """R-U-036/037/039/042: the refund, correct and operator-batch submit
    handlers all derive their Idempotency-Key via
    `crypto.subtle.digest(...)` (`app.js`'s `sha256Hex16`). `window.crypto.
    subtle` only exists in a Window.isSecureContext -- which the browser
    grants for `https:` origins and for the single special-cased hostname
    `localhost`/`127.0.0.1`, and for NOTHING else, including every other
    plain-HTTP origin: a LAN IP, a container's bridge-network IP, or any
    real deployment without TLS.

    This service is served over plain HTTP at a non-localhost address in
    every environment that matters here -- this factory's own
    `factory.gates.serve`/`gates.run` always hands out a docker bridge-
    network IP (e.g. `192.168.x.x:8080`), never `127.0.0.1`, and a real
    production deployment without HTTPS would have the identical origin
    shape. On such an origin `window.isSecureContext` is `false`,
    `window.crypto.subtle` is `undefined`, and calling `.digest(...)` on
    it throws a synchronous, uncaught `TypeError:
    Cannot read properties of undefined (reading 'digest')` -- inside the
    click handler, before any `fetch()` ever fires. All three of this
    item's new write paths (refund, correct, operator batch) are
    completely non-functional: no request is sent, no error slot is
    shown (the exception is thrown before the `.then()`/`.catch()` chain
    that would populate one), and the user sees nothing happen at all.

    Builder's own verification ran against `http://127.0.0.1:8099` --
    exactly the one HTTP origin where this defect is invisible, which is
    why it shipped.
    """
    uid_a, h_a = unique("u"), unique_handle("bza")
    uid_b, h_b = unique("u"), unique_handle("bzb")
    emails = [f"{h}@x.com" for h in (h_a, h_b)]
    reset_ok(make_fixture([user(uid_a, h_a, balance=1000, email=emails[0]),
                            user(uid_b, h_b, balance=0, email=emails[1])]))
    token_a = httpx.post(url("/auth/login"), json={"email": emails[0], "password": "password123"},
                          timeout=5).json()["token"]
    pay = httpx.post(url("/payments"), json={"to_handle": h_b, "amount": 100},
                      headers={**auth(token_a), "Idempotency-Key": unique("u3breach")}, timeout=5)
    assert pay.status_code == 201, pay.text
    pid = pay.json()["payment_id"]

    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    ui_login(page, emails[0], "password123")
    page.goto(url(f"/payments/{pid}"), wait_until="load")

    is_secure = page.evaluate("() => window.isSecureContext")
    has_subtle = page.evaluate("() => !!(window.crypto && window.crypto.subtle)")
    assert not is_secure and not has_subtle, (
        "this assumption changed -- if the served origin is now a secure context, re-examine whether "
        "the underlying defect is still reachable before treating this test as green"
    )

    page.fill(tid("correct-reason"), "typo fix")
    page.click(tid("correct-submit"))
    page.wait_for_timeout(1500)

    revisions = httpx.get(url(f"/payments/{pid}/revisions"), headers=auth(token_a), timeout=5).json()["revisions"]
    assert len(revisions) == 2 and not errors, (
        f"R-U-036/037/042: clicking correct-submit on a non-secure origin must still perform the "
        f"correction (or at minimum show a visible error to the user) -- it must never fail silently "
        f"with an uncaught exception and zero effect. Page errors: {errors!r}; revisions: {revisions!r}"
    )


def test_correct_double_click_on_unchanged_form_hits_idempotency_key_reuse_r_u_042(page):
    """R-U-042: 'a key derived from form content so an unchanged resubmit
    replays.' A genuinely rapid double-click (both dispatched inside a
    single `page.evaluate`, no Python/IPC round trip between them -- two
    sequential `page.click()` calls are too slow to reproduce this) on an
    UNCHANGED correct-form -- same amount, same reason, no field edited
    between clicks, the effective-instant field left at its default
    (blank) -- does NOT replay. `app.js`'s `effectiveInstant()` calls
    `new Date().toISOString()` fresh whenever the datetime-local field is
    empty, and that call happens inside the click handler itself, so the
    two clicks' request BODIES differ by a millisecond-scale timestamp
    even though the Idempotency-Key (now a stable `randomKey()`,
    regenerated only on an `input` event -- commit 8aac58e) is identical
    across both. The server correctly answers a same-key-different-body
    pair with `409 idempotency_key_reuse`, not a replay. Net effect:
    no double-spend (confirmed safe -- exactly one revision lands), but
    the second click surfaces a same-key-different-body CONFLICT for
    what the user did as a single unchanged double-click, contradicting
    R-U-042's stated guarantee. `correction_batches.py`'s UI binding has
    the identical `effectiveEl.value ? ... : new Date().toISOString()`
    pattern per row and shares this root cause (not re-tested here;
    same fix needed in both places)."""
    uid_a, h_a = unique("u"), unique_handle("dca")
    uid_b, h_b = unique("u"), unique_handle("dcb")
    emails = [f"{h}@x.com" for h in (h_a, h_b)]
    reset_ok(make_fixture([user(uid_a, h_a, balance=1000, email=emails[0]),
                            user(uid_b, h_b, balance=0, email=emails[1])]))
    token_a = httpx.post(url("/auth/login"), json={"email": emails[0], "password": "password123"},
                          timeout=5).json()["token"]
    pay = httpx.post(url("/payments"), json={"to_handle": h_b, "amount": 100},
                      headers={**auth(token_a), "Idempotency-Key": unique("dc")}, timeout=5)
    assert pay.status_code == 201, pay.text
    pid = pay.json()["payment_id"]

    responses = []
    page.on("response", lambda r: responses.append(r.status) if "corrections" in r.url else None)
    ui_login(page, emails[0], "password123")
    page.goto(url(f"/payments/{pid}"), wait_until="load")
    page.fill(tid("correct-reason"), "typo fix")
    page.evaluate(
        "() => { var b = document.querySelector('[data-testid=\"correct-submit\"]'); b.click(); b.click(); }"
    )
    page.wait_for_timeout(2000)

    assert responses == [201, 200], (
        f"R-U-042: a genuinely unchanged double-click must replay cleanly (one 201, the rest 200), "
        f"never a same-key-different-body conflict -- got {responses!r}"
    )
