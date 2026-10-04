"""`GET /me`, `POST /payments` and `GET /activity`: R-1-001..007, R-1-120,
R-1-130..140, R-1-190..196."""
from __future__ import annotations

import threading

from conftest import (api_get, api_post, assert_error, auth, idem, login_token, make_fixture,
                       reset_ok, two_user_fixture as _two_user_fixture, unique, unique_handle, user)


def test_get_me_shape():
    """R-1-120"""
    fixture, token_a, _ = _two_user_fixture(balance_a=777)
    r = api_get("/me", headers=auth(token_a))
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"user_id", "display_name", "handle", "balance", "currency", "minor_units"}
    assert body["balance"] == 777
    assert body["handle"] == fixture["users"][0]["handle"]


def test_payment_moves_money_atomically():
    """R-1-001, R-1-006, R-1-130"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=1000, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 400, "note": "x", "visibility": "public"},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 600
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 400


def test_payment_object_shape():
    """R-1-131"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    expected_keys = {"payment_id", "from_user_id", "from_handle", "to_user_id", "to_handle",
                      "amount", "currency", "note", "visibility", "request_id", "created_at", "settlement_id"}
    assert expected_keys <= set(body.keys())
    assert body["request_id"] is None
    assert body["settlement_id"] is None
    assert body["from_handle"] == fixture["users"][0]["handle"]
    assert body["to_handle"] == b_handle


def test_payment_defaults_note_and_visibility():
    """R-1-132"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 10}, headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["note"] == ""
    assert body["visibility"] == "public"


def test_insufficient_funds_409_no_change():
    """R-1-002, R-1-007, R-1-133"""
    fixture, token_a, token_b = _two_user_fixture(balance_a=5, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 6}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 409, "insufficient_funds")
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 5
    assert api_get("/me", headers=auth(token_b)).json()["balance"] == 0
    assert api_get("/activity", headers=auth(token_a)).json()["payments"] == []


def test_amount_range_rejected():
    """R-1-134"""
    fixture, token_a, _ = _two_user_fixture(balance_a=10**12)
    b_handle = fixture["users"][1]["handle"]
    for amount in (0, -1, 1_000_000_001, 10.5):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": amount},
                     headers={**auth(token_a), **idem(unique("k"))})
        assert_error(r, 422, "validation_failed")


def test_amount_boundaries_accepted():
    """R-1-134"""
    fixture, token_a, _ = _two_user_fixture(balance_a=2_000_000_000)
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1_000_000_000},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text


def test_payment_funds_boundary_exact_balance_succeeds_one_over_fails():
    """R-1-133, R-1-002: pins the `<` vs `<=` boundary in the funds check
    (a gate-6 mutation risk) — paying exactly the caller's balance succeeds
    and drains it to zero; one minor unit more than the balance is 409,
    on an otherwise-identical fresh fixture so the two cases can't interact."""
    fixture, token_a, _ = _two_user_fixture(balance_a=777, balance_b=0)
    b_handle = fixture["users"][1]["handle"]
    exact = api_post("/payments", json={"to_handle": b_handle, "amount": 777},
                      headers={**auth(token_a), **idem(unique("k"))})
    assert exact.status_code == 201, exact.text
    assert api_get("/me", headers=auth(token_a)).json()["balance"] == 0

    fixture2, token_a2, _ = _two_user_fixture(balance_a=777, balance_b=0)
    b2_handle = fixture2["users"][1]["handle"]
    over = api_post("/payments", json={"to_handle": b2_handle, "amount": 778},
                     headers={**auth(token_a2), **idem(unique("k"))})
    assert_error(over, 409, "insufficient_funds")


def test_self_payment_422():
    """R-1-135"""
    fixture, token_a, _ = _two_user_fixture()
    own_handle = fixture["users"][0]["handle"]
    r = api_post("/payments", json={"to_handle": own_handle, "amount": 1}, headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "self_payment")


def test_note_too_long_422():
    """R-1-136"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1, "note": "x" * 201},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_note_at_max_length_accepted():
    """R-1-136"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1, "note": "x" * 200},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text


def test_note_counted_in_code_points_emoji():
    """R-1-136, R-1-139"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    note = "\U0001F600" * 200  # 200 code points, emoji
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1, "note": note},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert r.json()["note"] == note


def test_visibility_invalid_value_422():
    """R-1-137"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1, "visibility": "secret"},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 422, "validation_failed")


def test_to_handle_no_owner_404():
    """R-1-138"""
    fixture, token_a, _ = _two_user_fixture()
    r = api_post("/payments", json={"to_handle": unique_handle("ghost"), "amount": 1},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert_error(r, 404, "not_found")


def test_note_verbatim_round_trip_unicode():
    """R-1-139"""
    fixture, token_a, _ = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    note = "  héllo wörld 日本語 🎉  "
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 1, "note": note},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    assert r.json()["note"] == note


def test_balance_stays_within_safe_integer_range():
    """R-1-140"""
    a_id, b_id = unique("u"), unique("u")
    a_handle, b_handle = unique_handle("a"), unique_handle("b")
    big = 2**53 - 100
    fixture = make_fixture([user(a_id, a_handle, balance=big), user(b_id, b_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    r = api_post("/payments", json={"to_handle": b_handle, "amount": 50}, headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    me = api_get("/me", headers=auth(token_a))
    assert me.json()["balance"] == big - 50


def test_activity_feed_shape_and_order():
    """R-1-190: pinned against the actual creation sequence (payment_id
    order), not against `created_at` strings — R-1-195 leaves same-second
    ties unspecified, so when every payment in a tight loop lands in the
    same second, `created == sorted(created, reverse=True)` is trivially
    true regardless of which direction the service actually sorts in (gate
    6 found exactly this: a flipped `reverse=True` -> `reverse=False` went
    undetected because this assertion couldn't tell the two apart)."""
    fixture, token_a, token_b = _two_user_fixture(balance_a=1000)
    b_handle = fixture["users"][1]["handle"]
    created_ids = []
    for i in range(4):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": 10},
                     headers={**auth(token_a), **idem(unique(f"k{i}"))})
        assert r.status_code == 201, r.text
        created_ids.append(r.json()["payment_id"])
    feed = api_get("/activity", headers=auth(token_a))
    assert feed.status_code == 200
    body = feed.json()
    assert "payments" in body and "has_more" in body
    returned_ids = [p["payment_id"] for p in body["payments"]]
    assert returned_ids == list(reversed(created_ids)), \
        f"activity must be newest-first by actual creation order: {returned_ids} vs expected {list(reversed(created_ids))}"


def test_activity_visibility_rule():
    """R-1-191, R-1-192, R-1-078: a private payment is hidden from a third
    party exactly as R-1-078 requires — this endpoint names no 403, so the
    hide-as-404-equivalent (here, simply absent from the feed) carve-out
    from R-1-078a does not apply."""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    token_b = login_token(fixture["users"][1]["email"])
    token_c = login_token(fixture["users"][2]["email"])

    pub = api_post("/payments", json={"to_handle": b_handle, "amount": 10, "visibility": "public"},
                   headers={**auth(token_a), **idem(unique("k"))})
    priv = api_post("/payments", json={"to_handle": b_handle, "amount": 10, "visibility": "private"},
                    headers={**auth(token_a), **idem(unique("k"))})
    assert pub.status_code == 201 and priv.status_code == 201

    pub_id, priv_id = pub.json()["payment_id"], priv.json()["payment_id"]

    # third party: sees only the public one
    third_feed = {p["payment_id"] for p in api_get("/activity", headers=auth(token_c)).json()["payments"]}
    assert pub_id in third_feed
    assert priv_id not in third_feed

    # sender sees both
    sender_feed = {p["payment_id"] for p in api_get("/activity", headers=auth(token_a)).json()["payments"]}
    assert pub_id in sender_feed and priv_id in sender_feed

    # receiver sees both, identically
    receiver_feed = {p["payment_id"] for p in api_get("/activity", headers=auth(token_b)).json()["payments"]}
    assert pub_id in receiver_feed and priv_id in receiver_feed


def test_requests_never_in_activity_feed():
    """R-1-193"""
    fixture, token_a, token_b = _two_user_fixture()
    b_handle = fixture["users"][1]["handle"]
    r = api_post("/requests", json={"payer_handle": b_handle, "amount": 10},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    feed = api_get("/activity", headers=auth(token_a))
    assert feed.json()["payments"] == []


def test_split_itself_not_a_feed_item():
    """R-1-193"""
    a_id, b_id, c_id = unique("u"), unique("u"), unique("u")
    a_handle, b_handle, c_handle = unique_handle("a"), unique_handle("b"), unique_handle("c")
    fixture = make_fixture([user(a_id, a_handle, balance=0), user(b_id, b_handle, balance=0),
                             user(c_id, c_handle, balance=0)])
    reset_ok(fixture)
    token_a = login_token(fixture["users"][0]["email"])
    r = api_post("/splits", json={"amount": 9, "participant_handles": [a_handle, b_handle, c_handle]},
                 headers={**auth(token_a), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    feed = api_get("/activity", headers=auth(token_a))
    assert feed.json()["payments"] == []


def test_activity_remains_correct_under_concurrent_writes():
    """R-1-195: relative order of same-second payments and pagination
    stability under concurrent writes are unspecified — this test asserts
    only that every payment shows up and the service stays correct (5xx-free),
    never a specific order or a stable page boundary."""
    fixture, token_a, _ = _two_user_fixture(balance_a=1000)
    b_handle = fixture["users"][1]["handle"]
    created_ids = []
    lock = threading.Lock()

    def one(i):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": 1},
                     headers={**auth(token_a), **idem(unique(f"k{i}"))})
        assert r.status_code == 201, r.text
        with lock:
            created_ids.append(r.json()["payment_id"])

    threads = [threading.Thread(target=one, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    feed = api_get("/activity", headers=auth(token_a), params={"limit": 200})
    assert feed.status_code == 200
    seen_ids = {p["payment_id"] for p in feed.json()["payments"]}
    assert set(created_ids) <= seen_ids


def test_activity_limit_offset_and_has_more():
    """R-1-194"""
    fixture, token_a, _ = _two_user_fixture(balance_a=1000)
    b_handle = fixture["users"][1]["handle"]
    for i in range(5):
        r = api_post("/payments", json={"to_handle": b_handle, "amount": 1}, headers={**auth(token_a), **idem(unique(f"k{i}"))})
        assert r.status_code == 201, r.text
    page1 = api_get("/activity", headers=auth(token_a), params={"limit": 2, "offset": 0})
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["payments"]) == 2
    assert body1["has_more"] is True

    past_end = api_get("/activity", headers=auth(token_a), params={"limit": 2, "offset": 100})
    assert past_end.json()["payments"] == []
    assert past_end.json()["has_more"] is False


def test_activity_limit_and_offset_invalid_422():
    """R-1-073, R-1-074, R-1-194"""
    fixture, token_a, _ = _two_user_fixture()
    for bad_limit in (0, 201, -1, "abc"):
        r = api_get("/activity", headers=auth(token_a), params={"limit": bad_limit})
        assert_error(r, 422, "validation_failed")
    for bad_offset in (-1, "abc"):
        r = api_get("/activity", headers=auth(token_a), params={"offset": bad_offset})
        assert_error(r, 422, "validation_failed")


def test_settlement_member_payment_follows_feed_visibility_rule():
    """R-1-196"""
    a_id, b_id, op_id, third_id = unique("u"), unique("u"), unique("u"), unique("u")
    a_handle, b_handle, op_handle, third_handle = (unique_handle("a"), unique_handle("b"),
                                                    unique_handle("op"), unique_handle("c"))
    fixture = make_fixture(
        [user(a_id, a_handle, balance=1000), user(b_id, b_handle, balance=0),
         user(op_id, op_handle, balance=0), user(third_id, third_handle, balance=0)],
        settlement_operator_ids=[op_id],
    )
    reset_ok(fixture)
    token_op = login_token(fixture["users"][2]["email"])
    token_third = login_token(fixture["users"][3]["email"])
    r = api_post("/settlements", json={"transfers": [{"from_handle": a_handle, "to_handle": b_handle,
                                                        "amount": 10, "visibility": "private"}]},
                 headers={**auth(token_op), **idem(unique("k"))})
    assert r.status_code == 201, r.text
    payment_id = r.json()["payments"][0]["payment_id"]
    third_feed = {p["payment_id"] for p in api_get("/activity", headers=auth(token_third)).json()["payments"]}
    assert payment_id not in third_feed
