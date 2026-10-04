"""Adversarial findings against N1-2 (fixture/reset, login, /me, GET /requests).

Fails against commit 8cc8661.
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import login, make_fixture, reset_ok, unique_email, user  # noqa: E402


def test_login_timing_does_not_distinguish_unknown_email_from_wrong_password():
    """R-1-086: 'Login with a wrong password or an unknown email is
    401 unauthenticated, with no distinction between the two cases.'

    `routes/auth.py`'s `LoginEndpoint.apply` does
    `user = STORE.users_by_email.get(email); if user is None or not
    verify_password(...)`. Short-circuit evaluation means an unknown email
    never pays the ~120,000-iteration PBKDF2 cost that a wrong password
    for a real account does — a wall-clock side channel that lets a caller
    distinguish the two cases (and so enumerate registered emails) even
    though the status code and body are identical.
    """
    email = unique_email("timing")
    reset_ok(make_fixture([user("tu1", "timinguser", email=email)]))

    def sample(email_to_try: str, password: str, n: int = 12) -> list[float]:
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            login(email_to_try, password)
            times.append(time.perf_counter() - t0)
        return times

    unknown_email_times = sample(unique_email("neverexisted"), "whatever-wrong")
    wrong_password_times = sample(email, "whatever-wrong")

    unknown_median = statistics.median(unknown_email_times)
    wrong_pw_median = statistics.median(wrong_password_times)

    assert wrong_pw_median < unknown_median * 3, (
        f"login timing leaks which case occurred: unknown-email median="
        f"{unknown_median * 1000:.3f}ms, wrong-password median="
        f"{wrong_pw_median * 1000:.3f}ms (ratio={wrong_pw_median / unknown_median:.1f}x). "
        "An unknown email short-circuits before hashing; a wrong password for a "
        "real account pays the full PBKDF2 cost, so the two 'identical' 401s are "
        "trivially distinguishable by wall-clock time."
    )
