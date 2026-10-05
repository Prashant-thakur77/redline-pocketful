"""Adversarial findings against N3-3 (GET /statement + snapshot paging).

Fails against commit 52513a8.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import api_get, api_post, auth, idem, two_user_fixture, unique  # noqa: E402


def _statement(token, **params):
    r = api_get("/statement", headers=auth(token), params=params or None)
    assert r.status_code == 200, f"GET /statement failed: {r.status_code} {r.text}"
    return r.json()


def test_snapshot_token_must_be_echoed_unchanged_across_pages_r_3_090():
    """R-3-090: 'A snapshot-paged response echoes the same `snapshot` token
    it was given, so a caller can page without retaining the first
    response. Returning a *new* token per page would contradict R-3-081's
    freeze.'

    The implementation instead mints a token that encodes the *next*
    offset (`f"{snapshot_id}.{start_offset + limit}"`), so every page
    after the first returns a different `snapshot` string than the one it
    was given. A caller who wants page 3 but only kept the *first*
    response's token (as R-3-090 explicitly promises they can) is stuck:
    passing that stale token back with a bigger `offset` is silently
    treated as an unrecognized/foreign snapshot and a brand-new window is
    minted instead (losing the freeze guaranteed by R-3-081).
    """
    fixture, token_a, _ = two_user_fixture(balance_a=5000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    for amount in range(1, 8):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert r.status_code == 201, r.text

    page1 = _statement(token_a, limit=2)
    first_token = page1["snapshot"]
    assert first_token is not None

    # R-3-090: paging further with the *same* token the caller already has,
    # advancing only via `offset`, must keep returning that same token.
    page2 = _statement(token_a, limit=2, offset=2, snapshot=first_token)
    assert page2["snapshot"] == first_token, (
        f"page 2 echoed a different snapshot token ({page2['snapshot']!r}) "
        f"than it was given ({first_token!r}), violating R-3-090"
    )

    page3 = _statement(token_a, limit=2, offset=4, snapshot=first_token)
    assert page3["snapshot"] == first_token, (
        f"page 3 echoed a different snapshot token ({page3['snapshot']!r}) "
        f"than it was given ({first_token!r}), violating R-3-090"
    )
    # And the frozen window must still be intact: page 3 must actually
    # advance past page 2 using the same first_token + offset, not restart
    # a brand-new window (which is what happens today once the token
    # string no longer matches any key in STORE.statement_snapshots).
    assert [e["payment_id"] for e in page3["entries"]] not in ([], [e["payment_id"] for e in page2["entries"]])
