"""Adversarial findings against N1-3 (signup: derived handle, email/handle
uniqueness, password rules).
"""
from __future__ import annotations

import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import signup, unique_email  # noqa: E402


def test_concurrent_signups_same_email_exactly_one_201():
    """R-1-088 / R-1-083: two concurrent signups racing the same email must
    produce exactly one 201 and the rest 409 email_taken, never two 201s
    (which would mean two accounts, or one account double-inserted and the
    wallet/token bookkeeping corrupted).

    `SignupEndpoint.apply` checks `email in STORE.users_by_email` and does
    the insert in the same `apply()`, which the pipeline runs under the
    store's write lock — this test is the race that claim depends on;
    nothing in the existing suite exercises it.
    """
    email = unique_email("racer")

    def attempt(_i):
        return signup(email=email, password="password123", display_name="Racer").status_code

    with ThreadPoolExecutor(20) as pool:
        statuses = list(pool.map(attempt, range(20)))

    counts = Counter(statuses)
    assert counts[201] == 1, f"expected exactly one 201, got {dict(counts)}"
    assert counts[409] == 19, f"expected the other 19 to be 409 email_taken, got {dict(counts)}"
    assert all(s in (201, 409) for s in statuses), f"unexpected status: {dict(counts)}"


def test_concurrent_signups_colliding_derived_handle_exactly_one_201():
    """R-1-088: two different emails that derive to the *same* handle
    (`a.b@x.com` and `a_b@y.com` both -> `a_b`) racing concurrently must
    still produce exactly one 201 for that handle; the rest 409
    handle_taken, never two accounts sharing one handle."""
    run = unique_email("hcol").split("@")[0]
    separators = list(".-+~^!#$%&*=?|;:")
    # Every local part substitutes its separator to "_" and derives to the
    # same handle (f"{run}_tail"); each email string is distinct (different
    # separator / domain), so this race is decided by handle_taken, not
    # email_taken.
    emails = [f"{run}{sep}tail@collider{i}.example.com" for i, sep in enumerate(separators)]

    def attempt(email):
        return signup(email=email, password="password123", display_name="Collider").status_code

    with ThreadPoolExecutor(16) as pool:
        statuses = list(pool.map(attempt, emails))

    counts = Counter(statuses)
    assert counts[201] == 1, f"expected exactly one 201 across colliding handles, got {dict(counts)}"
    assert counts.get(409, 0) == len(emails) - 1, f"expected the rest 409, got {dict(counts)}"
