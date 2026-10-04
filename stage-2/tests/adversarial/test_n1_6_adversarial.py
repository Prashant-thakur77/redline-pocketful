"""Adversarial findings against N1-6 (requests lifecycle: POST /requests,
/requests/{id}/pay|decline|cancel)."""
from __future__ import annotations

import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, login_token,  # noqa: E402
                      make_fixture, reset_ok, unique, unique_handle, user)


def _three_users(requester_balance=0, payer_balance=10_000, third_balance=10_000):
    r_id, p_id, t_id = unique("u"), unique("u"), unique("u")
    r_handle, p_handle, t_handle = unique_handle("req"), unique_handle("pay"), unique_handle("3rd")
    r_email, p_email, t_email = f"{r_handle}@example.com", f"{p_handle}@example.com", f"{t_handle}@example.com"
    reset_ok(make_fixture([
        user(r_id, r_handle, balance=requester_balance, email=r_email),
        user(p_id, p_handle, balance=payer_balance, email=p_email),
        user(t_id, t_handle, balance=third_balance, email=t_email),
    ]))
    return {
        "requester": {"id": r_id, "handle": r_handle, "token": login_token(r_email)},
        "payer": {"id": p_id, "handle": p_handle, "token": login_token(p_email)},
        "third": {"id": t_id, "handle": t_handle, "token": login_token(t_email)},
    }


def _create_request(requester_token, payer_handle, amount, note=None):
    body = {"payer_handle": payer_handle, "amount": amount}
    if note is not None:
        body["note"] = note
    r = api_post("/requests", json=body, headers=auth_idem(requester_token, unique("mkreq")))
    assert r.status_code == 201, r.text
    return r.json()["request_id"]


def _pay_request(req_id, token, key, visibility=None):
    body = {} if visibility is None else {"visibility": visibility}
    return api_post(f"/requests/{req_id}/pay", json=body, headers=auth_idem(token, key))


def _decline_request(req_id, token):
    return api_post(f"/requests/{req_id}/decline", json={}, headers=auth(token))


def _cancel_request(req_id, token):
    return api_post(f"/requests/{req_id}/cancel", json={}, headers=auth(token))


def test_unrelated_third_party_pay_is_403_not_404():
    """R-1-158: 'a caller who is not the request's payer (including a
    third party) is 403 forbidden' — this explicitly overrides R-1-078's
    general hide-as-nonexistent rule for this endpoint. The code's
    `PayRequestEndpoint.check_resource_permission` currently treats a
    caller who is neither the requester nor the payer as if the request
    didn't exist (404), which matches R-1-078's *general* pattern but
    contradicts R-1-158's specific, explicit carve-out: "including a
    third party" only makes sense if a genuine outsider gets 403, not
    404 — a non-payer is a non-payer whether or not they're also a
    stranger to the request.
    """
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    r = _pay_request(req_id, users["third"]["token"], unique("thirdpay"))
    assert_error(r, 403, "forbidden")


def test_unrelated_third_party_decline_is_403_not_404():
    """R-1-160: 'a non-payer is 403 forbidden' — same carve-out as pay."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    r = _decline_request(req_id, users["third"]["token"])
    assert_error(r, 403, "forbidden")


def test_unrelated_third_party_cancel_is_403_not_404():
    """R-1-161: 'a non-requester is 403 forbidden' — same carve-out."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    r = _cancel_request(req_id, users["third"]["token"])
    assert_error(r, 403, "forbidden")


def test_r_1_241_concurrent_pays_different_keys_exactly_one_winner():
    """R-1-241: two concurrent pays of the same pending request by the
    payer with DIFFERENT idempotency keys — the idempotency layer cannot
    save this (different keys), only the in-lock live status check can.
    Exactly one 201, the rest 409 request_not_pending, money moves once."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    def attempt(i):
        return _pay_request(req_id, users["payer"]["token"], unique(f"pay241-{i}"))

    with ThreadPoolExecutor(10) as pool:
        responses = list(pool.map(attempt, range(10)))

    statuses = Counter(r.status_code for r in responses)
    assert statuses[201] == 1, f"expected exactly one 201, got {dict(statuses)}"
    assert statuses[409] == 9, f"expected 9 request_not_pending, got {dict(statuses)}"
    for r in responses:
        if r.status_code == 409:
            assert r.json()["error"]["code"] == "request_not_pending", r.text

    bal = api_get("/me", headers=auth(users["requester"]["token"])).json()["balance"]
    assert bal == 100, f"money must move exactly once, got requester balance {bal}"


def test_decline_racing_pay_exactly_one_winner():
    """Decline racing pay on the same pending request: exactly one winner
    (either the payment succeeds and decline gets 409, or decline wins
    and pay gets 409) — never two winners, never a 500."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    def do_pay():
        return ("pay", _pay_request(req_id, users["payer"]["token"], unique("racepay")))

    def do_decline():
        return ("decline", _decline_request(req_id, users["payer"]["token"]))

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda f: f(), [do_pay, do_decline]))

    outcomes = dict(results)
    assert all(r.status_code < 500 for _, r in results), f"no 5xx allowed: {outcomes}"

    pay_r, decline_r = outcomes["pay"], outcomes["decline"]
    pay_ok = pay_r.status_code == 201
    decline_ok = decline_r.status_code == 200
    assert pay_ok != decline_ok, (
        f"exactly one of pay/decline must win, got pay={pay_r.status_code} decline={decline_r.status_code}"
    )
    loser = decline_r if pay_ok else pay_r
    assert loser.status_code == 409 and loser.json()["error"]["code"] == "request_not_pending", (
        f"the loser must be 409 request_not_pending, got {loser.status_code}: {loser.text}"
    )


def test_cancel_racing_pay_exactly_one_winner():
    """Same race, cancel (by the requester) vs pay (by the payer)."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    def do_pay():
        return ("pay", _pay_request(req_id, users["payer"]["token"], unique("racepay2")))

    def do_cancel():
        return ("cancel", _cancel_request(req_id, users["requester"]["token"]))

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda f: f(), [do_pay, do_cancel]))

    outcomes = dict(results)
    assert all(r.status_code < 500 for _, r in results), f"no 5xx allowed: {outcomes}"

    pay_r, cancel_r = outcomes["pay"], outcomes["cancel"]
    pay_ok = pay_r.status_code == 201
    cancel_ok = cancel_r.status_code == 200
    assert pay_ok != cancel_ok, (
        f"exactly one of pay/cancel must win, got pay={pay_r.status_code} cancel={cancel_r.status_code}"
    )
    loser = cancel_r if pay_ok else pay_r
    assert loser.status_code == 409 and loser.json()["error"]["code"] == "request_not_pending", (
        f"the loser must be 409 request_not_pending, got {loser.status_code}: {loser.text}"
    )


def test_r_1_159_replay_during_concurrent_unrelated_decline():
    """R-1-159: replaying a successful pay must return 200 with the
    original payment body, never 409 request_not_pending, even while
    another thread is concurrently declining a *different* request (so
    the idempotency store and the write lock are both under concurrent
    pressure at the same time)."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)
    other_req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 50)

    key = unique("replaypay")
    r1 = _pay_request(req_id, users["payer"]["token"], key)
    assert r1.status_code == 201, r1.text
    original_body = r1.json()

    def replay():
        return _pay_request(req_id, users["payer"]["token"], key)

    def unrelated_decline():
        return _decline_request(other_req_id, users["payer"]["token"])

    with ThreadPoolExecutor(10) as pool:
        replays = list(pool.map(lambda _: replay(), range(8)))
        declines = list(pool.map(lambda _: unrelated_decline(), range(2)))

    for r in replays:
        assert r.status_code == 200, f"replay must be 200, got {r.status_code}: {r.text}"
        assert r.json() == original_body, f"replay body must be verbatim: {r.json()} != {original_body}"
    assert declines[0].status_code == 200
    assert declines[1].status_code == 200  # decline is idempotent-by-nature too


def test_cross_transition_precedence_decline_vs_cancel_race():
    """R-1-160/161: double-decline and double-cancel are each 200
    (idempotent-by-nature), but a decline racing a cancel on the SAME
    pending request must have exactly one winner, and the loser must get
    409 request_not_pending — the lenient 200 only applies to repeating
    the SAME transition, never to the opposite one."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    def do_decline():
        return ("decline", _decline_request(req_id, users["payer"]["token"]))

    def do_cancel():
        return ("cancel", _cancel_request(req_id, users["requester"]["token"]))

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda f: f(), [do_decline, do_cancel]))

    outcomes = dict(results)
    decline_r, cancel_r = outcomes["decline"], outcomes["cancel"]
    decline_ok = decline_r.status_code == 200
    cancel_ok = cancel_r.status_code == 200
    assert decline_ok != cancel_ok, (
        f"exactly one of decline/cancel must win this race, got decline={decline_r.status_code} "
        f"cancel={cancel_r.status_code}"
    )
    loser = cancel_r if decline_ok else decline_r
    assert loser.status_code == 409 and loser.json()["error"]["code"] == "request_not_pending", (
        f"the loser of a decline-vs-cancel race must be 409 request_not_pending, got "
        f"{loser.status_code}: {loser.text}"
    )


def test_declining_a_cancelled_request_is_409_not_200():
    """R-1-160/161 cross-transition: declining an already-cancelled
    request is 409 request_not_pending, not the lenient 200 that only
    applies to repeating decline-on-declined."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    r_cancel = _cancel_request(req_id, users["requester"]["token"])
    assert r_cancel.status_code == 200, r_cancel.text

    r_decline = _decline_request(req_id, users["payer"]["token"])
    assert_error(r_decline, 409, "request_not_pending")


def test_cancelling_a_declined_request_is_409_not_200():
    """Symmetric case: cancelling an already-declined request is 409."""
    users = _three_users()
    req_id = _create_request(users["requester"]["token"], users["payer"]["handle"], 100)

    r_decline = _decline_request(req_id, users["payer"]["token"])
    assert r_decline.status_code == 200, r_decline.text

    r_cancel = _cancel_request(req_id, users["requester"]["token"])
    assert_error(r_cancel, 409, "request_not_pending")


def test_r_1_162_decline_and_cancel_move_no_money_under_concurrent_payments():
    """R-1-162: decline and cancel move no money, ever. Hammer 10
    requests with concurrent decline/cancel/pay attempts and verify the
    total money in the two-party system is conserved regardless of which
    transition won each one."""
    users = _three_users(requester_balance=0, payer_balance=10_000)
    total_before = 10_000

    req_ids = [_create_request(users["requester"]["token"], users["payer"]["handle"], 100) for _ in range(10)]

    def attempt(i, req_id):
        action = i % 3
        if action == 0:
            return _pay_request(req_id, users["payer"]["token"], unique(f"conspay{i}"))
        elif action == 1:
            return _decline_request(req_id, users["payer"]["token"])
        else:
            return _cancel_request(req_id, users["requester"]["token"])

    with ThreadPoolExecutor(10) as pool:
        list(pool.map(lambda args: attempt(*args), enumerate(req_ids)))

    bal_requester = api_get("/me", headers=auth(users["requester"]["token"])).json()["balance"]
    bal_payer = api_get("/me", headers=auth(users["payer"]["token"])).json()["balance"]
    assert bal_requester + bal_payer == total_before, (
        f"conservation violated: {bal_requester} + {bal_payer} != {total_before}"
    )
    assert bal_requester >= 0 and bal_payer >= 0
