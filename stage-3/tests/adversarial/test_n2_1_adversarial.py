"""Adversarial findings against N2-1 (the derived holds model: R-2-001..005,
R-2-010..028, R-2-030..034)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, authorization,  # noqa: E402
                      login_token, make_fixture, reset_ok, unique, unique_handle, user)


def _iso(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat()


def test_available_blocks_a_payment_that_total_would_allow():
    """R-2-002/R-2-013: with an open hold, a payment that fits `total` but
    not `available` must be 409 insufficient_funds — the exact behaviour
    change stage 2 introduces over stage 1.

    Built manually, not via `two_user_fixture`: that helper generates its
    own internal user ids and does not expose them before `reset_ok` runs,
    so an `authorization(...)` built from a separately-`unique("u")`'d id
    would reference a user that doesn't exist in the fixture it seeds
    (exactly the bug @builder caught in d2f2cba: both callers of
    `two_user_fixture` here minted their own a_id/b_id and got a spurious
    422 unknown-user instead of the intended 409)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("pa"), unique_handle("pb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=700)],
    ))
    a_token = login_token(f"{a_handle}@example.com")

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 1000 and me["held"] == 700 and me["available"] == 300

    r = api_post("/payments", json={"to_handle": b_handle, "amount": 500},
                 headers=auth_idem(a_token, unique("blocked")))
    assert_error(r, 409, "insufficient_funds")

    r_ok = api_post("/payments", json={"to_handle": b_handle, "amount": 300},
                     headers=auth_idem(a_token, unique("fits")))
    assert r_ok.status_code == 201, r_ok.text


def test_available_blocks_a_request_pay_that_total_would_allow():
    """Same R-2-013 rule, via POST /requests/{id}/pay. Built manually for
    the same reason as above."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("qa"), unique_handle("qb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=700)],
    ))
    a_token = login_token(f"{a_handle}@example.com")
    b_token = login_token(f"{b_handle}@example.com")

    r_req = api_post("/requests", json={"payer_handle": a_handle, "amount": 500},
                      headers=auth_idem(b_token, unique("mkreq")))
    assert r_req.status_code == 201, r_req.text
    request_id = r_req.json()["request_id"]

    r_pay = api_post(f"/requests/{request_id}/pay", json={}, headers=auth_idem(a_token, unique("paywithhold")))
    assert_error(r_pay, 409, "insufficient_funds")


def test_available_blocks_settlement_net_debit_that_total_would_allow():
    """R-2-017: a settlement's net debit must be checked against
    available, not total. Operator = a, hold on a, settle a->b 500
    (fits a's total of 1000, not a's available of 300)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("opa"), unique_handle("opb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=700)],
        settlement_operator_ids=[a_id],
    ))
    op_token = login_token(f"{a_handle}@example.com")
    r = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle, "amount": 500}]},
                 headers=auth_idem(op_token, unique("settlehold")))
    assert_error(r, 409, "insufficient_funds")


def test_held_sums_multiple_open_authorizations_not_just_one():
    """R-2-004/R-2-024: check_holds_within_balance and held_for must sum
    ALL of the caller's open authorizations, not just check the first
    one individually. Two holds of 400 each against a balance of 700:
    individually affordable, together not — reset must reject this."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("ma"), unique_handle("mb"), unique_handle("mc")
    r = api_post("/_test/reset", json=make_fixture(
        [user(a_id, a_handle, balance=700, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com"),
         user(c_id, c_handle, balance=0, email=f"{c_handle}@example.com")],
        authorizations=[
            authorization(unique("auth"), a_id, b_id, amount=400),
            authorization(unique("auth"), a_id, c_id, amount=400),
        ],
    ))
    assert_error(r, 422, "validation_failed")


def test_held_sums_multiple_open_authorizations_when_affordable():
    """Converse: two holds of 300 each against a balance of 700 (600
    total held, 100 available) must be accepted, and GET /me must
    report the summed held/available correctly."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("sa"), unique_handle("sb"), unique_handle("sc")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=700, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com"),
         user(c_id, c_handle, balance=0, email=f"{c_handle}@example.com")],
        authorizations=[
            authorization(unique("auth"), a_id, b_id, amount=300),
            authorization(unique("auth"), a_id, c_id, amount=300),
        ],
    ))
    me = api_get("/me", headers=auth(login_token(f"{a_handle}@example.com"))).json()
    assert me["held"] == 600, me
    assert me["available"] == 100, me


def test_expired_seeded_authorization_holds_nothing_immediately():
    """R-2-030/R-2-032: a seeded `open` authorization whose expires_at is
    already in the past must hold nothing in GET /me's available, with
    no write having occurred — pure read-time derivation."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ea"), unique_handle("eb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=700,
                                       expires_at=_iso(timedelta(hours=-2)))],
    ))
    me = api_get("/me", headers=auth(login_token(f"{a_handle}@example.com"))).json()
    assert me["held"] == 0, f"an expired hold must not count toward held: {me}"
    assert me["available"] == 1000, me

    feed = api_get("/authorizations", headers=auth(login_token(f"{a_handle}@example.com"))).json()
    assert feed["authorizations"][0]["status"] == "expired"
    assert feed["authorizations"][0]["remaining_amount"] == 0


def test_authorization_expiring_exactly_at_now_boundary_is_expired():
    """R-2-034: expiry must be exact to the instant — expires_at a
    fraction of a second in the past (not comfortably hours away) must
    already read as expired, never as a lingering open hold."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("xa"), unique_handle("xb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=500, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=300,
                                       expires_at=_iso(timedelta(seconds=-1)))],
    ))
    me = api_get("/me", headers=auth(login_token(f"{a_handle}@example.com"))).json()
    assert me["available"] == 500, f"a hold expired 1s ago must already release: {me}"


def test_get_authorizations_hides_from_unrelated_third_party():
    """R-2-080: an authorization is visible only to its payer and
    receiver — a third, unrelated user must not see it at all."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ta"), unique_handle("tb")
    aid = unique("auth")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(aid, a_id, b_id, amount=300)],
    ))
    from conftest import signup_ok
    third = signup_ok()
    feed = api_get("/authorizations", headers=auth(third["token"])).json()
    ids = {a["authorization_id"] for a in feed["authorizations"]}
    assert aid not in ids, "an unrelated third party must not see someone else's authorization"


def test_held_never_counts_incoming_authorization():
    """R-2-004: held is the sum over the caller's OUTGOING authorizations
    only — the receiver of a hold must show held: 0 for it."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ia"), unique_handle("ib")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=500, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=700)],
    ))
    me_b = api_get("/me", headers=auth(login_token(f"{b_handle}@example.com"))).json()
    assert me_b["held"] == 0, f"the receiver of a hold must not have it counted against them: {me_b}"
    assert me_b["available"] == 500


def test_captured_amount_out_of_range_rejected_by_reset():
    """R-2-028: captured_amount outside 0..amount is 422."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("ca"), unique_handle("cb")
    r = api_post("/_test/reset", json=make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=300, captured_amount=301)],
    ))
    assert_error(r, 422, "validation_failed")


def test_authorization_self_reference_rejected_by_reset():
    """R-2-027: from_user_id == to_user_id is 422."""
    a_id = unique("u")
    a_handle = unique_handle("sfa")
    r = api_post("/_test/reset", json=make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, a_id, amount=300)],
    ))
    assert_error(r, 422, "validation_failed")


def test_authorization_unknown_user_rejected_by_reset():
    """R-2-027: a reference to an unknown user id is 422."""
    a_id = unique("u")
    a_handle = unique_handle("una")
    r = api_post("/_test/reset", json=make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, "no-such-user-id", amount=300)],
    ))
    assert_error(r, 422, "validation_failed")


def test_authorization_invalid_status_rejected_by_reset():
    """R-2-025: a seeded status outside open/captured/voided/expired is 422."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("iva"), unique_handle("ivb")
    r = api_post("/_test/reset", json=make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, b_id, amount=300, status="pending")],
    ))
    assert_error(r, 422, "validation_failed")


def test_non_positive_ttl_rejected_by_reset():
    """R-2-020: a non-positive authorization_ttl_seconds is 422."""
    a_id = unique("u")
    a_handle = unique_handle("ttla")
    r = api_post("/_test/reset", json=make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com")],
        authorization_ttl_seconds=0,
    ))
    assert_error(r, 422, "validation_failed")


def test_closed_authorization_does_not_block_despite_amount():
    """A voided or captured authorization must not count toward held even
    though its amount is nonzero — only `open` (and unexpired) holds
    funds (R-2-005)."""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("cla"), unique_handle("clb")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com")],
        authorizations=[
            authorization(unique("auth"), a_id, b_id, amount=700, status="voided"),
            authorization(unique("auth"), a_id, b_id, amount=700, status="captured"),
        ],
    ))
    me = api_get("/me", headers=auth(login_token(f"{a_handle}@example.com"))).json()
    assert me["held"] == 0, f"voided/captured holds must not count: {me}"
    assert me["available"] == 1000


def test_concurrent_payments_against_available_never_go_negative_with_open_hold():
    """R-2-002 under concurrency: with an open hold reducing available
    below total, concurrent payments must still never push available (or
    total) negative — the same drain-to-zero attack as stage 1's R-1-002
    target, now with a hold in the mix."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("cca"), unique_handle("ccb"), unique_handle("ccc")
    reset_ok(make_fixture(
        [user(a_id, a_handle, balance=1000, email=f"{a_handle}@example.com"),
         user(b_id, b_handle, balance=0, email=f"{b_handle}@example.com"),
         user(c_id, c_handle, balance=0, email=f"{c_handle}@example.com")],
        authorizations=[authorization(unique("auth"), a_id, c_id, amount=400)],
    ))
    a_token = login_token(f"{a_handle}@example.com")
    # available = 1000 - 400 = 600; fire 10 payments of 100 each (room for
    # exactly 6) with 10 different keys.
    from concurrent.futures import ThreadPoolExecutor

    def attempt(i):
        return api_post("/payments", json={"to_handle": b_handle, "amount": 100},
                         headers=auth_idem(a_token, unique(f"drain{i}")))

    with ThreadPoolExecutor(10) as pool:
        responses = list(pool.map(attempt, range(10)))

    statuses = [r.status_code for r in responses]
    assert statuses.count(201) == 6, f"expected exactly 6 successes (600 available / 100), got {statuses}"
    assert statuses.count(409) == 4, statuses

    me = api_get("/me", headers=auth(a_token)).json()
    assert me["total"] == 400, me
    assert me["available"] == 0, me
    assert me["held"] == 400, me
