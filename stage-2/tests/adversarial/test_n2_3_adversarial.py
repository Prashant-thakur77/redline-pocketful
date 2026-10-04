"""Adversarial findings against N2-3 (capture/void: R-2-050..075).

Planner's two flagged risk areas — R-2-005 double-release (a capture
racing a void must have exactly one winner, never both) and R-2-066
(a capture within the remainder must never fail for funds even at
available=0) — plus the state-machine edge cases around them. All held
against commit 07052a8; nothing here currently fails."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, authorization,  # noqa: E402
                      login_token, make_fixture, reset_ok, signup_ok, unique, unique_handle, user)


def _two_party_hold(balance_a=1000, auth_amount=1000, expires_at=None):
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ha"), unique_handle("hb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=balance_a, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=auth_amount, expires_at=expires_at)],
    ))
    auth_id = api_get("/authorizations", headers=auth(login_token(f"{a_handle}@example.com"))).json()["authorizations"][0]["authorization_id"]
    a_token = login_token(f"{a_handle}@example.com")
    b_token = login_token(f"{b_handle}@example.com")
    return auth_id, a_token, b_token


def test_capture_within_remainder_never_fails_for_funds_at_zero_available():
    """R-2-066: the entire balance is held by one authorization (available
    == 0); capturing the full remainder must still succeed, because the
    hold already reserved the money — this must never be checked against
    `available_for()`."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=1000, auth_amount=1000)
    me = api_get("/me", headers=auth(a_token)).json()
    assert me["available"] == 0 and me["held"] == 1000

    r = api_post(f"/authorizations/{auth_id}/capture", json={}, headers=auth_idem(b_token, unique("cap")))
    assert r.status_code == 201, r.text

    me_after = api_get("/me", headers=auth(a_token)).json()
    assert me_after == {**me_after, "total": 0, "available": 0, "held": 0}


def test_partial_final_capture_releases_exact_remainder_immediately():
    """R-2-056: capturing 1500 of a 2000 hold with final=true (default)
    must release exactly the 500 remainder in the same step — not more,
    not less, not on a delay."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=2000, auth_amount=2000)
    r = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 1500, "final": True},
                 headers=auth_idem(b_token, unique("partial")))
    assert r.status_code == 201, r.text

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 500, me
    assert me["available"] == 500, me
    assert me["held"] == 0, me


def test_capture_vs_void_race_never_double_releases():
    """R-2-005: a capture and a void racing on the same authorization must
    have exactly one winner. Checked both ways: if the capture wins,
    total/available must land at 0 (money moved, hold gone); if the void
    wins, total/available must land back at the original balance (hold
    released, no money moved). Never both, never neither, never a value
    in between (which would mean the hold was released twice or the
    capture's debit landed without the hold being cleared)."""
    for _trial in range(15):
        auth_id, a_token, b_token = _two_party_hold(balance_a=1000, auth_amount=1000)
        results = {}

        def do_capture():
            r = api_post(f"/authorizations/{auth_id}/capture", json={}, headers=auth_idem(b_token, unique("race")))
            results["capture"] = r

        def do_void():
            r = api_post(f"/authorizations/{auth_id}/void", json={}, headers=auth(a_token))
            results["void"] = r

        t1 = threading.Thread(target=do_capture)
        t2 = threading.Thread(target=do_void)
        t1.start(); t2.start()
        t1.join(timeout=5.0); t2.join(timeout=5.0)

        capture_won = results["capture"].status_code == 201
        void_won = results["void"].status_code == 200 and results["void"].json()["status"] == "voided"
        assert capture_won != void_won, (
            f"exactly one must win (trial {_trial}): capture={results['capture'].status_code}, "
            f"void={results['void'].status_code} {results['void'].text}"
        )

        me = api_get("/me", headers=auth(a_token)).json()
        if capture_won:
            assert me["total"] == 0 and me["available"] == 0 and me["held"] == 0, (_trial, me)
        else:
            assert me["total"] == 1000 and me["available"] == 1000 and me["held"] == 0, (_trial, me)


def test_overcommit_race_never_overcaptures_the_authorization():
    """15 concurrent partial captures of 100 each (final=false) against a
    remainder of 1000: at most 10 can succeed. The moment the 10th lands,
    the authorization auto-closes (R-2-059), so every later attempt — even
    one that would individually fit 100 against a nonexistent remainder —
    correctly sees `409 authorization_not_open`, not an overcapture and
    not a stray `422`. Total captured must sum to exactly 1000, never
    more."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=1000, auth_amount=1000)
    outs = []
    lock = threading.Lock()

    def partial_capture(i):
        r = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 100, "final": False},
                     headers=auth_idem(b_token, unique(f"oc{i}")))
        with lock:
            outs.append(r.status_code)

    threads = [threading.Thread(target=partial_capture, args=(i,)) for i in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    successes = [s for s in outs if s == 201]
    assert len(successes) == 10, f"exactly 10 of 15 must succeed (1000/100): {outs}"
    assert all(s in (201, 409) for s in outs), f"no capture_exceeds expected once remainder hits exactly 0: {outs}"

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 0 and me["available"] == 0 and me["held"] == 0, me


def test_capture_exceeding_nonzero_remainder_is_capture_exceeds_not_not_open():
    """Distinguishes the two 409/422 paths deterministically (no race):
    while a nonzero remainder is still open, requesting more than it must
    be 422 capture_exceeds_authorization — the authorization_not_open
    case above only applies once the remainder has actually hit zero and
    the hold has closed."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=1000, auth_amount=1000)
    for i in range(9):
        r = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 100, "final": False},
                     headers=auth_idem(b_token, unique(f"d{i}")))
        assert r.status_code == 201, r.text

    r = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 150, "final": False},
                 headers=auth_idem(b_token, unique("exceeds")))
    assert_error(r, 422, "capture_exceeds_authorization")


def test_capture_after_final_close_is_not_open_not_capture_exceeds():
    """A capture attempt after a final capture has already closed the
    authorization must be 409 authorization_not_open (R-2-057) — the
    amount-vs-remainder comparison never runs on a closed hold."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=2000, auth_amount=2000)
    r1 = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 500, "final": True},
                  headers=auth_idem(b_token, unique("first")))
    assert r1.status_code == 201, r1.text

    r2 = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 1},
                  headers=auth_idem(b_token, unique("second")))
    assert_error(r2, 409, "authorization_not_open")


def test_void_after_autoclose_via_accumulated_captures_is_not_open():
    """An authorization that auto-closed because accumulated final=false
    captures reached exactly its remainder (R-2-059) must reject a void
    with 409 authorization_not_open, not silently succeed and not be
    treated as the still-open case."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=1000, auth_amount=1000)
    r1 = api_post(f"/authorizations/{auth_id}/capture", json={"amount": 1000, "final": False},
                  headers=auth_idem(b_token, unique("full")))
    assert r1.status_code == 201, r1.text

    r2 = api_post(f"/authorizations/{auth_id}/void", json={}, headers=auth(a_token))
    assert_error(r2, 409, "authorization_not_open")


def test_double_void_is_idempotent_and_releases_nothing_twice():
    """R-2-072: voiding an already-voided authorization is 200 with the
    current state, and must not credit `available` a second time."""
    auth_id, a_token, b_token = _two_party_hold(balance_a=1000, auth_amount=1000)
    r1 = api_post(f"/authorizations/{auth_id}/void", json={}, headers=auth(a_token))
    assert r1.status_code == 200, r1.text
    r2 = api_post(f"/authorizations/{auth_id}/void", json={}, headers=auth(a_token))
    assert r2.status_code == 200 and r2.json()["status"] == "voided", r2.text

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 1000 and me["available"] == 1000 and me["held"] == 0, me


def test_stranger_on_expired_authorization_gets_forbidden_not_a_state_error():
    """Permission precedes state checks (R-1-075/R-2-064): a caller who is
    neither party gets 403 even when the authorization is also expired —
    never the 409 the real parties would see."""
    import datetime
    expired = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)).isoformat()
    auth_id, a_token, b_token = _two_party_hold(balance_a=500, auth_amount=500, expires_at=expired)
    stranger = signup_ok()

    r = api_post(f"/authorizations/{auth_id}/capture", json={}, headers=auth_idem(stranger["token"], unique("strexp")))
    assert_error(r, 403, "forbidden")

    r = api_post(f"/authorizations/{auth_id}/void", json={}, headers=auth(stranger["token"]))
    assert_error(r, 403, "forbidden")


def test_capturing_one_of_two_independent_holds_leaves_the_other_open():
    """Two independent authorizations from the same payer: capturing one
    must not touch the other's status or the amount it still holds."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("ia"), unique_handle("ib"), unique_handle("ic")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com"),
         user(c_id, c_handle, balance=0, email=f"{c_handle}@example.com")],
        authorizations=[
            authorization(unique("auth"), a_id, b_id, amount=400),
            authorization(unique("auth"), a_id, c_id, amount=300),
        ],
    ))
    a_token = login_token(f"{a_handle}@example.com")
    b_token = login_token(f"{b_handle}@example.com")
    feed = api_get("/authorizations", headers=auth(a_token)).json()["authorizations"]
    by_amount = {a["amount"]: a for a in feed}
    auth1_id = by_amount[400]["authorization_id"]
    auth2_id = by_amount[300]["authorization_id"]

    r = api_post(f"/authorizations/{auth1_id}/capture", json={}, headers=auth_idem(b_token, unique("cap1")))
    assert r.status_code == 201, r.text

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 600 and me["held"] == 300 and me["available"] == 300, me

    feed2 = api_get("/authorizations", headers=auth(a_token)).json()["authorizations"]
    statuses = {a["authorization_id"]: a["status"] for a in feed2}
    assert statuses[auth1_id] == "captured"
    assert statuses[auth2_id] == "open"
