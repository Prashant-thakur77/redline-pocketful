"""Adversarial findings against N1-8 (POST /settlements)."""
from __future__ import annotations

import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from conftest import (api_get, api_post, assert_error, auth, auth_idem, login_token,  # noqa: E402
                      make_fixture, reset_ok, unique, unique_handle, user)


def _users(balances: dict, operator_handles: tuple[str, ...] = ()):
    """balances: {label: balance}. Returns {label: {id, handle, token, email}}."""
    specs = {}
    for label, bal in balances.items():
        uid, handle = unique("u"), unique_handle(label[:3])
        email = f"{handle}@example.com"
        specs[label] = {"id": uid, "handle": handle, "email": email, "balance": bal}

    operator_ids = [specs[label]["id"] for label in operator_handles]
    reset_ok(make_fixture(
        [user(s["id"], s["handle"], balance=s["balance"], email=s["email"]) for s in specs.values()],
        settlement_operator_ids=operator_ids,
    ))
    out = {}
    for label, s in specs.items():
        out[label] = {**s, "token": login_token(s["email"])}
    return out


def _settle(token, transfers, key=None):
    key = key or unique("settle")
    return api_post("/settlements", json={"transfers": transfers},
                     headers=auth_idem(token, key))


def _balance(token):
    return api_get("/me", headers=auth(token)).json()["balance"]


def test_r_1_227_pass_through_zero_balance_intermediary_either_order():
    """R-1-227: ada(100)->bob 100, bob(0)->cy 100. bob nets to zero as a
    pure pass-through. Must succeed in EITHER order — the order where
    bob's own transfer-out is listed before ada's transfer-in is exactly
    what catches a sequential (not net) affordability check."""
    u = _users({"ada": 100, "bob": 0, "cy": 0}, operator_handles=("ada",))

    forward = [
        {"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 100},
        {"from_handle": u["bob"]["handle"], "to_handle": u["cy"]["handle"], "amount": 100},
    ]
    r_forward = _settle(u["ada"]["token"], forward)
    assert r_forward.status_code == 201, f"forward order must succeed: {r_forward.text}"
    assert _balance(u["ada"]["token"]) == 0
    assert _balance(u["bob"]["token"]) == 0
    assert _balance(u["cy"]["token"]) == 100

    u2 = _users({"ada": 100, "bob": 0, "cy": 0}, operator_handles=("ada",))
    reverse = [
        {"from_handle": u2["bob"]["handle"], "to_handle": u2["cy"]["handle"], "amount": 100},
        {"from_handle": u2["ada"]["handle"], "to_handle": u2["bob"]["handle"], "amount": 100},
    ]
    r_reverse = _settle(u2["ada"]["token"], reverse)
    assert r_reverse.status_code == 201, (
        f"reverse order (bob's transfer-out listed before ada's transfer-in) must also succeed "
        f"under a true NET affordability check: {r_reverse.text}"
    )
    assert _balance(u2["ada"]["token"]) == 0
    assert _balance(u2["bob"]["token"]) == 0
    assert _balance(u2["cy"]["token"]) == 100


def test_r_1_227_negative_net_rejected_and_changes_nothing_regardless_of_order():
    """Converse of the above: a wallet whose NET across the batch is
    negative is 409 insufficient_funds and changes nothing. ada starts at
    50 and sends two separate 50-unit transfers (each individually
    'affordable' if checked against her starting balance in isolation),
    netting -100 overall — no reordering of two same-direction debits can
    make that affordable, and the whole batch must be rejected with
    neither leg applied."""
    u = _users({"ada": 50, "bob": 0, "cy": 0}, operator_handles=("ada",))
    transfers = [
        {"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 50},
        {"from_handle": u["ada"]["handle"], "to_handle": u["cy"]["handle"], "amount": 50},
    ]

    r = _settle(u["ada"]["token"], transfers)
    assert_error(r, 409, "insufficient_funds")
    assert _balance(u["ada"]["token"]) == 50, "a rejected settlement must change nothing"
    assert _balance(u["bob"]["token"]) == 0
    assert _balance(u["cy"]["token"]) == 0


def test_r_1_226_entry_order_precedence_first_entry_error_wins():
    """R-1-226: entry errors take precedence in INPUT order, regardless of
    error-code severity. Entry 0 has a bad amount (422); entry 1 has an
    unknown handle (404). Entry 0's error must win."""
    u = _users({"ada": 1000, "bob": 0}, operator_handles=("ada",))
    transfers = [
        {"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 0},  # bad amount, entry 0
        {"from_handle": u["ada"]["handle"], "to_handle": "nosuchhandle0000", "amount": 10},  # unknown, entry 1
    ]
    r = _settle(u["ada"]["token"], transfers)
    assert_error(r, 422, "validation_failed")

    # Reversed: now the unknown-handle entry is first and must win, even
    # though 404 and 422 swapped places — proving it's genuinely about
    # input order, not "422 always beats 404" or vice versa.
    transfers_reversed = [
        {"from_handle": u["ada"]["handle"], "to_handle": "nosuchhandle0000", "amount": 10},  # entry 0
        {"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 0},  # entry 1
    ]
    r2 = _settle(u["ada"]["token"], transfers_reversed)
    assert_error(r2, 404, "not_found")


def test_r_1_226_entry_errors_precede_insufficient_funds():
    """R-1-226: all entry errors take precedence over 409
    insufficient_funds, even when the unaffordable entry comes first."""
    u = _users({"ada": 10}, operator_handles=("ada",))
    transfers = [
        {"from_handle": u["ada"]["handle"], "to_handle": u["ada"]["handle"], "amount": 5},  # self_payment
        {"from_handle": u["ada"]["handle"], "to_handle": u["ada"]["handle"], "amount": 10_000_000},  # unaffordable too
    ]
    r = _settle(u["ada"]["token"], transfers)
    assert_error(r, 422, "self_payment")


def test_r_1_229_failed_settlement_claims_no_idempotency_key():
    """R-1-229: a settlement that fails validation or affordability claims
    NO idempotency key — the same key must be reusable afterward as a
    genuine first use, same shape as the R-1-107 x R-1-108 payments
    interaction."""
    u = _users({"ada": 10, "bob": 0}, operator_handles=("ada",))
    key = unique("settle-fail-release")

    bad_transfers = [{"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 10_000}]
    r1 = _settle(u["ada"]["token"], bad_transfers, key=key)
    assert_error(r1, 409, "insufficient_funds")

    good_transfers = [{"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 5}]
    r2 = _settle(u["ada"]["token"], good_transfers, key=key)
    assert r2.status_code == 201, (
        f"same key after a failed settlement must be a fresh first use, got {r2.status_code}: {r2.text}"
    )


def test_r_1_231_shared_timestamp_across_all_members():
    """R-1-231: every member shares one created_at, identical across all
    and equal to committed_at."""
    u = _users({"ada": 1000, "bob": 0, "cy": 0, "dan": 0}, operator_handles=("ada",))
    transfers = [
        {"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 10},
        {"from_handle": u["ada"]["handle"], "to_handle": u["cy"]["handle"], "amount": 20},
        {"from_handle": u["ada"]["handle"], "to_handle": u["dan"]["handle"], "amount": 30},
    ]
    r = _settle(u["ada"]["token"], transfers)
    assert r.status_code == 201, r.text
    body = r.json()
    timestamps = {p["created_at"] for p in body["payments"]}
    assert len(timestamps) == 1, f"every member must share one created_at, got {timestamps}"
    assert timestamps.pop() == body["committed_at"], "created_at must equal committed_at"


def test_r_1_222_operator_permission_does_not_widen_visibility():
    """R-1-222: being a settlement operator must not grant visibility into
    another user's requests or private activity. The operator here is not
    a party to either resource and must get the normal non-party
    treatment (404 on the request, absence from the private payment's
    activity feed) exactly as a non-operator would."""
    u = _users({"ada": 1000, "bob": 1000, "op": 1000}, operator_handles=("op",))

    r_req = api_post("/requests", json={"payer_handle": u["bob"]["handle"], "amount": 50},
                      headers=auth_idem(u["ada"]["token"], unique("mkreq")))
    assert r_req.status_code == 201, r_req.text
    request_id = r_req.json()["request_id"]

    r_pay = api_post("/payments", json={"to_handle": u["bob"]["handle"], "amount": 10, "visibility": "private"},
                      headers=auth_idem(u["ada"]["token"], unique("privpay")))
    assert r_pay.status_code == 201, r_pay.text
    payment_id = r_pay.json()["payment_id"]

    r_decline = api_post(f"/requests/{request_id}/decline", json={}, headers=auth(u["op"]["token"]))
    assert_error(r_decline, 403, "forbidden")

    feed = api_get("/activity", headers=auth(u["op"]["token"])).json()
    ids = {p["payment_id"] for p in feed["payments"]}
    assert payment_id not in ids, "settlement operator must not see an unrelated private payment"


def test_r_1_228_concurrent_settlement_atomicity_under_sustained_reads():
    """R-1-228: either all movements of a settlement commit together or
    none do. Run a 20-transfer settlement (fan-out from one operator to
    20 recipients) while a background poller hammers GET /me for the
    operator throughout; every observed balance must be exactly the
    starting balance or exactly the final balance — never a value in
    between that would indicate a partially-applied batch."""
    n = 20
    per_transfer = 10
    balances = {"op": n * per_transfer}
    for i in range(n):
        balances[f"r{i}"] = 0
    u = _users(balances, operator_handles=("op",))

    initial = n * per_transfer
    observed = []
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            r = api_get("/me", headers=auth(u["op"]["token"]))
            if r.status_code == 200:
                observed.append(r.json()["balance"])

    poller = threading.Thread(target=poll)
    poller.start()

    transfers = [{"from_handle": u["op"]["handle"], "to_handle": u[f"r{i}"]["handle"], "amount": per_transfer}
                 for i in range(n)]
    r = _settle(u["op"]["token"], transfers)

    stop.set()
    poller.join(timeout=5.0)

    assert r.status_code == 201, r.text
    assert observed, "the poller must have captured at least one reading"
    bad = [v for v in observed if v not in (initial, 0)]
    assert not bad, f"observed a partially-applied settlement balance: {bad} (only {initial} or 0 are valid)"


def test_r_1_236_operators_own_handle_on_one_side_is_not_self_payment():
    """R-1-236: self_payment applies only within one entry
    (from_handle == to_handle); an operator's own handle on one side of
    a transfer with a DIFFERENT counterparty is perfectly legal."""
    u = _users({"op": 1000, "bob": 0}, operator_handles=("op",))
    transfers = [{"from_handle": u["op"]["handle"], "to_handle": u["bob"]["handle"], "amount": 100}]
    r = _settle(u["op"]["token"], transfers)
    assert r.status_code == 201, r.text


def test_non_operator_cannot_settle():
    """R-1-221: an authenticated non-operator is 403 forbidden."""
    u = _users({"ada": 1000, "bob": 0}, operator_handles=())
    transfers = [{"from_handle": u["ada"]["handle"], "to_handle": u["bob"]["handle"], "amount": 10}]
    r = _settle(u["ada"]["token"], transfers)
    assert_error(r, 403, "forbidden")
