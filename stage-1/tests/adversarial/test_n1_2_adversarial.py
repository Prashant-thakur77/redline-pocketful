"""Adversarial findings against N1-2 (fixture/reset, login, /me, GET /requests).

Fails against commit 8cc8661.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import login, make_fixture, reset_ok, unique_email, user  # noqa: E402


def test_login_timing_does_not_distinguish_unknown_email_from_wrong_password():
    """R-1-086 / R-1-086a: 'no distinction between the two cases' includes
    wall-clock time — an unknown email must pay the same password-
    verification cost as a wrong password against a real account.

    Use the **minimum** of many samples, not the median or mean. CPU
    scheduling noise on a shared/loaded box only ever adds latency to a
    sample; it never makes a request finish faster than the work it
    actually did. So the floor across many samples is the honest measure
    of each path's cost, and a short-circuit shows up as a near-zero
    floor that noise cannot mask — where a median/mean-based comparison
    can false-pass: inflated unknown-email samples from scheduler jitter
    can make a noisy median/mean look close to the real PBKDF2 cost even
    while the code still short-circuits (confirmed in practice: the
    previous median-ratio form of this test passed twice against the
    vulnerable commit `5b4bc54`).

    Phrased as "the unknown-email path must be slow too" (not "the
    wrong-password path must be fast") — that is the direction an
    `X is None or <expensive check>` short-circuit actually breaks.
    """
    email = unique_email("timing")
    reset_ok(make_fixture([user("tu1", "timinguser", email=email)]))

    def sample(email_to_try: str, password: str, n: int = 25) -> list[float]:
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            login(email_to_try, password)
            times.append(time.perf_counter() - t0)
        return times

    unknown_email_times = sample(unique_email("neverexisted"), "whatever-wrong")
    wrong_password_times = sample(email, "whatever-wrong")

    unknown_floor = min(unknown_email_times)
    wrong_pw_floor = min(wrong_password_times)

    assert unknown_floor > wrong_pw_floor * 0.5, (
        f"login timing leaks which case occurred: unknown-email floor="
        f"{unknown_floor * 1000:.3f}ms, wrong-password floor="
        f"{wrong_pw_floor * 1000:.3f}ms (ratio={wrong_pw_floor / unknown_floor:.1f}x "
        "wrong-password:unknown-email). An unknown email must pay the same "
        "password-verification cost (a fixed dummy hash) as a wrong password "
        "against a real account; a short-circuit on `user is None` makes the "
        "unknown-email path a near-free dict miss instead."
    )
