"""Atomic net settlements: R-1-220..236."""
from __future__ import annotations

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, unique, unique_handle, user)


def _setup(n=4, balance=1000, operators=1):
    ids = [unique("u") for _ in range(n)]
    handles = [unique_handle(f"p{i}") for i in range(n)]
    fixture = make_fixture([user(ids[i], handles[i], balance=balance) for i in range(n)],
                            settlement_operator_ids=ids[:operators])
    reset_ok(fixture)
    tokens = [login_token(fixture["users"][i]["email"]) for i in range(n)]
    return fixture, ids, handles, tokens


def test_settlement_requires_operator_and_key():
    """R-1-221"""
    fixture, ids, handles, tokens = _setup()
    no_auth = api_post("/settlements", json={"transfers": []}, headers={"Idempotency-Key": "k"})
    assert_error(no_auth, 401, "unauthenticated")

    non_operator = api_post("/settlements", json={"transfers": []}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert_error(non_operator, 403, "forbidden")

    missing_key = api_post("/settlements", json={"transfers": []}, headers=auth(tokens[0]))
    assert_error(missing_key, 400, "missing_idempotency_key")


def test_operator_grants_only_settlement_execution():
    """R-1-222"""
    fixture, ids, handles, tokens = _setup(n=3)
    # a request between two non-operator users, private to them
    other_a, other_b = tokens[1], tokens[2]
    r = api_post("/requests", json={"payer_handle": handles[2], "amount": 10},
                 headers={**auth(other_a), **idem(unique("k"))})
    req_id = r.json()["request_id"]
    pay = api_post("/payments", json={"to_handle": handles[2], "amount": 5, "visibility": "private"},
                   headers={**auth(other_a), **idem(unique("k"))})
    assert pay.status_code == 201

    operator_token = tokens[0]
    # operator cannot see the non-operator's private activity or requests any differently
    op_feed = api_get("/activity", headers=auth(operator_token)).json()["payments"]
    assert all(p["payment_id"] != pay.json()["payment_id"] for p in op_feed)
    op_requests = api_get("/requests", headers=auth(operator_token)).json()["requests"]
    assert all(x["request_id"] != req_id for x in op_requests)


def test_settlement_body_shape_and_defaults():
    """R-1-223"""
    fixture, ids, handles, tokens = _setup()
    r = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[2], "amount": 10}]},
                 headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    payment = r.json()["payments"][0]
    assert payment["note"] == ""
    assert payment["visibility"] == "public"


def test_settlement_batch_shape_errors():
    """R-1-224"""
    fixture, ids, handles, tokens = _setup()
    for bad in (None, "not-array", [], [{"from_handle": handles[1], "to_handle": handles[2], "amount": 1}] * 33):
        body = {} if bad is None else {"transfers": bad}
        r = api_post("/settlements", json=body, headers={**auth(tokens[0]), **idem(unique("k"))})
        assert_error(r, 422, "validation_failed")


def test_settlement_per_entry_errors():
    """R-1-225"""
    fixture, ids, handles, tokens = _setup(n=3)

    unknown = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": unique_handle("ghost"), "amount": 10}]},
                        headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(unknown, 404, "not_found")

    self_pay = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[1], "amount": 10}]},
                         headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(self_pay, 422, "self_payment")

    bad_amount = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[2], "amount": -1}]},
                           headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(bad_amount, 422, "validation_failed")

    bad_note = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[2],
                                                               "amount": 10, "note": "x" * 201}]},
                         headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(bad_note, 422, "validation_failed")

    bad_vis = api_post("/settlements", json={"transfers": [{"from_handle": handles[1], "to_handle": handles[2],
                                                              "amount": 10, "visibility": "nope"}]},
                        headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(bad_vis, 422, "validation_failed")


def test_entry_errors_precede_insufficient_funds_in_input_order():
    """R-1-226"""
    fixture, ids, handles, tokens = _setup(n=4, balance=0)
    transfers = [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 1000},  # would be insufficient_funds
        {"from_handle": handles[2], "to_handle": unique_handle("ghost"), "amount": 10},  # 404 comes first by index... wait both at different indices
    ]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(tokens[0]), **idem(unique("k"))})
    # entry 0 is itself affordable-or-not only decided after validation; entry[1] has a 404 field error.
    # Since entry errors take precedence in input order over insufficient_funds (which is batch-level),
    # the first entry with any error — here entry index 1's unknown handle — determines the response
    # only if entry 0 has no field error of its own. Entry 0 has no field error, so the unknown handle at
    # index 1 is the first entry error found and wins over the batch's insufficient_funds.
    assert_error(r, 404, "not_found")


def test_affordable_net_zero_batch_succeeds_even_if_single_leg_would_not():
    """R-1-227"""
    fixture, ids, handles, tokens = _setup(n=2, balance=0)
    # handles[0] has balance 0; it sends 100 to handles[1] and receives 100 back in the same batch.
    transfers = [
        {"from_handle": handles[0], "to_handle": handles[1], "amount": 100},
        {"from_handle": handles[1], "to_handle": handles[0], "amount": 100},
    ]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 0
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 0


def test_unaffordable_net_batch_rejected_and_changes_nothing():
    """R-1-227, R-1-229"""
    fixture, ids, handles, tokens = _setup(n=2, balance=50)
    transfers = [{"from_handle": handles[0], "to_handle": handles[1], "amount": 100}]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 409, "insufficient_funds")
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 50
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 50


def test_settlement_funds_boundary_exact_balance_succeeds_one_over_fails():
    """R-1-227: pins the `<` vs `<=` boundary in settlement net-affordability
    specifically (a separate code path from a direct payment's funds check,
    so each needs its own boundary test) — a single-leg transfer for
    exactly the sender's balance succeeds, draining it to zero; one minor
    unit more is 409, on a fresh fixture so the two cases can't interact."""
    fixture, ids, handles, tokens = _setup(n=2, balance=500)
    exact = api_post("/settlements", json={"transfers": [{"from_handle": handles[0], "to_handle": handles[1], "amount": 500}]},
                      headers={**auth(tokens[0]), **idem(unique("k1"))})
    assert exact.status_code == 201, exact.text
    assert api_get("/me", headers=auth(tokens[0])).json()["balance"] == 0

    fixture2, ids2, handles2, tokens2 = _setup(n=2, balance=500)
    over = api_post("/settlements", json={"transfers": [{"from_handle": handles2[0], "to_handle": handles2[1], "amount": 501}]},
                    headers={**auth(tokens2[0]), **idem(unique("k2"))})
    assert_error(over, 409, "insufficient_funds")


def _chain_fixture():
    """ada (100) -> bob (0) -> cy (0): bob's own starting balance cannot
    cover his outgoing leg, and only nets to zero because of ada's earlier
    entry in the SAME batch. Stricter than a mutual pair: a per-wallet net
    check passes it, a running-balance-in-input-order simulation also
    happens to pass it (since ada's credit lands before bob's debit in
    forward order), but checking each leg against the wallet's STARTING
    balance does not."""
    ada_id, bob_id, cy_id = unique("u"), unique("u"), unique("u")
    ada, bob, cy = unique_handle("ada"), unique_handle("bob"), unique_handle("cy")
    fixture = make_fixture(
        [user(ada_id, ada, balance=100), user(bob_id, bob, balance=0), user(cy_id, cy, balance=0)],
        settlement_operator_ids=[ada_id],
    )
    reset_ok(fixture)
    token_ada = login_token(fixture["users"][0]["email"])
    token_bob = login_token(fixture["users"][1]["email"])
    token_cy = login_token(fixture["users"][2]["email"])
    return (token_ada, ada), (token_bob, bob), (token_cy, cy)


def test_net_affordability_chain_through_intermediary_forward_order():
    """R-1-227: bob is a pass-through with zero starting balance; his
    outgoing leg exceeds it, but his net across the batch is zero. Must
    succeed, ending ada at 0, bob at 0, cy at 100."""
    (token_ada, ada), (token_bob, bob), (token_cy, cy) = _chain_fixture()
    transfers = [
        {"from_handle": ada, "to_handle": bob, "amount": 100},
        {"from_handle": bob, "to_handle": cy, "amount": 100},
    ]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(token_ada), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(token_ada)).json()["balance"] == 0
    assert api_get("/me", headers=auth(token_bob)).json()["balance"] == 0
    assert api_get("/me", headers=auth(token_cy)).json()["balance"] == 100


def test_net_affordability_chain_through_intermediary_reverse_order():
    """R-1-227: the same chain with its transfers listed in reverse order
    (bob->cy BEFORE ada->bob) must still succeed — affordability is about net
    position, not about there existing a feasible sequential ordering. An
    implementation that simulates strictly in input order fails this one
    even though it happens to pass the forward-order case above."""
    (token_ada, ada), (token_bob, bob), (token_cy, cy) = _chain_fixture()
    transfers = [
        {"from_handle": bob, "to_handle": cy, "amount": 100},
        {"from_handle": ada, "to_handle": bob, "amount": 100},
    ]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(token_ada), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(token_ada)).json()["balance"] == 0
    assert api_get("/me", headers=auth(token_bob)).json()["balance"] == 0
    assert api_get("/me", headers=auth(token_cy)).json()["balance"] == 100


def test_settlement_atomic_all_or_nothing():
    """R-1-228"""
    fixture, ids, handles, tokens = _setup(n=3, balance=100)
    transfers = [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 50},
        {"from_handle": handles[2], "to_handle": handles[1], "amount": 1000},  # unaffordable net
    ]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert_error(r, 409, "insufficient_funds")
    assert api_get("/me", headers=auth(tokens[1])).json()["balance"] == 100
    assert api_get("/me", headers=auth(tokens[2])).json()["balance"] == 100


def test_failed_settlement_claims_no_key_and_creates_nothing():
    """R-1-229"""
    fixture, ids, handles, tokens = _setup(n=2, balance=10)
    key = unique("retry-after-fail")
    bad = api_post("/settlements", json={"transfers": [{"from_handle": handles[0], "to_handle": handles[1], "amount": 1000}]},
                   headers={**auth(tokens[0]), **idem(key)})
    assert_error(bad, 409, "insufficient_funds")
    # the same key can now be used for a different, successful settlement (first use, not a reuse conflict)
    good = api_post("/settlements", json={"transfers": [{"from_handle": handles[0], "to_handle": handles[1], "amount": 5}]},
                    headers={**auth(tokens[0]), **idem(key)})
    assert good.status_code == 201, good.text


def test_successful_settlement_response_shape():
    """R-1-230, R-1-231, R-1-232"""
    fixture, ids, handles, tokens = _setup(n=3, balance=1000)
    transfers = [
        {"from_handle": handles[1], "to_handle": handles[2], "amount": 10},
        {"from_handle": handles[2], "to_handle": handles[1], "amount": 3},
    ]
    r = api_post("/settlements", json={"transfers": transfers}, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    assert {"settlement_id", "committed_at", "payments"} <= set(body.keys())
    payments = body["payments"]
    assert len(payments) == 2
    assert payments[0]["from_handle"] == handles[1] and payments[0]["to_handle"] == handles[2]
    assert payments[1]["from_handle"] == handles[2] and payments[1]["to_handle"] == handles[1]
    for p in payments:
        assert p["settlement_id"] == body["settlement_id"]
        assert p["request_id"] is None
        assert p["created_at"] == body["committed_at"]

    # a payment outside any settlement has settlement_id null
    direct = api_post("/payments", json={"to_handle": handles[2], "amount": 1}, headers={**auth(tokens[1]), **idem(unique("k"))})
    assert direct.json()["settlement_id"] is None


def test_replaying_settlement_moves_no_additional_money():
    """R-1-233"""
    fixture, ids, handles, tokens = _setup(n=2, balance=1000)
    key = unique("settle-key")
    body = {"transfers": [{"from_handle": handles[0], "to_handle": handles[1], "amount": 10}]}
    r1 = api_post("/settlements", json=body, headers={**auth(tokens[0]), **idem(key)})
    assert r1.status_code == 201, r1.text
    before = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    r2 = api_post("/settlements", json=body, headers={**auth(tokens[0]), **idem(key)})
    assert r2.status_code == 200, r2.text
    assert r1.json() == r2.json()
    after = api_get("/me", headers=auth(tokens[0])).json()["balance"]
    assert before == after


def test_settlement_ignores_unknown_fields():
    """R-1-234, R-1-022"""
    fixture, ids, handles, tokens = _setup(n=2, balance=1000)
    body = {"transfers": [{"from_handle": handles[0], "to_handle": handles[1], "amount": 10, "mystery": True}],
            "another_unknown_field": 123}
    r = api_post("/settlements", json=body, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text


def test_operator_self_transfer_entries_permitted():
    """R-1-236"""
    fixture, ids, handles, tokens = _setup(n=2, balance=1000, operators=2)
    # operator's own handle appears as from_handle in one entry and to_handle in another,
    # but never both within the SAME entry.
    body = {"transfers": [
        {"from_handle": handles[0], "to_handle": handles[1], "amount": 10},
        {"from_handle": handles[1], "to_handle": handles[0], "amount": 4},
    ]}
    r = api_post("/settlements", json=body, headers={**auth(tokens[0]), **idem(unique("k"))})
    assert r.status_code == 201, r.text
