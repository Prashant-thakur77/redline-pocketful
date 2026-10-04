"""Gate hook for pocketful stage 1 — see factory/gates/hook.py for the
contract. Imports the same demo fixture the pytest suite uses, so stage 2's
first screen is never empty and the storm exercises real-looking data.

`snapshot`/`populate`/`carry` (gate 5) must stay correct across every later
stage: stage-1/tests/ is copied forward into stage-2, stage-3 and stage-4, so
this file is the one gate 5 runs for every upgrade, not just stage 1 -> 2.
`snapshot` therefore only fingerprints facts that must survive ANY correct
upgrade (balances, pre-upgrade token identity, known request states, settlement
membership, idempotent-retry identity) and never anything version-specific
such as the raw `/_test/export` document, whose shape later stages legitimately
extend.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from demo_fixture import build_demo_fixture  # noqa: E402

TIMEOUT = 10.0


def _url(base_url: str, path: str) -> str:
    return base_url.rstrip("/") + path


def _get(base_url, path, headers=None, params=None):
    return httpx.get(_url(base_url, path), headers=headers, params=params, timeout=TIMEOUT)


def _post(base_url, path, json=None, headers=None):
    return httpx.post(_url(base_url, path), json=json, headers=headers, timeout=TIMEOUT)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# setup / operation / invariant / transient — required by gate 4 (storm)
# ---------------------------------------------------------------------------

def setup(base_url: str) -> dict:
    fixture = build_demo_fixture()
    r = _post(base_url, "/_test/reset", json=fixture)
    assert r.status_code == 204, f"reset failed: {r.status_code} {r.text}"

    users = []
    for u in fixture["users"]:
        lr = _post(base_url, "/auth/login", json={"email": u["email"], "password": u["password"]})
        assert lr.status_code == 200, f"login failed for {u['handle']}: {lr.status_code} {lr.text}"
        users.append({"id": u["id"], "handle": u["handle"], "token": lr.json()["token"],
                      "seed_balance": u["balance"]})

    # the operator is u-alice (see demo_fixture.SETTLEMENT_OPERATOR_IDS)
    operator = next(u for u in users if u["id"] == fixture["settlement_operator_ids"][0])

    pending_requests = [
        {"id": req["id"], "requester_id": req["requester_id"], "payer_id": req["payer_id"]}
        for req in fixture["requests"] if req["status"] == "pending"
    ]

    # open-by-seed-status authorizations: targets for the storm's capture/void
    # slices. Includes the seeded-open-but-already-expired one on purpose, so
    # the storm actually exercises R-2-030's expiry path, not just R-2-181/182.
    seed_auth_targets = [
        {"id": a["id"], "from_user_id": a["from_user_id"], "to_user_id": a["to_user_id"]}
        for a in fixture.get("authorizations", []) if a["status"] == "open"
    ]

    return {
        "fixture": fixture,
        "users": users,
        "operator": operator,
        "seeded_total": sum(u["balance"] for u in fixture["users"]),
        "pending_requests": pending_requests,
        "seed_auth_targets": seed_auth_targets,
        "n": len(users),
        "lock": threading.Lock(),
        "split_receipts": [],
        "paid_request_ids": set(),
    }


def _pick(ctx, i, offset=0):
    users = ctx["users"]
    return users[(i + offset) % len(users)]


def _settlement_boundary_op(base_url, ctx, i, key):
    """R-1-227: one variant is individually unaffordable per leg but nets to
    zero (must succeed), the other is collectively unaffordable (must 409)."""
    operator = ctx["operator"]
    a = _pick(ctx, i)
    b = _pick(ctx, i, offset=1)
    if (i // 11) % 2 == 0:
        amount = a["seed_balance"] + 777  # neither leg alone is affordable, but they cancel out
        transfers = [
            {"from_handle": a["handle"], "to_handle": b["handle"], "amount": amount},
            {"from_handle": b["handle"], "to_handle": a["handle"], "amount": amount},
        ]
    else:
        amount = a["seed_balance"] + 500  # one-way: always net-unaffordable for a
        transfers = [{"from_handle": a["handle"], "to_handle": b["handle"], "amount": amount}]
    r = _post(base_url, "/settlements", json={"transfers": transfers},
              headers={**_auth(operator["token"]), "Idempotency-Key": key})
    return r.status_code


def _payment_boundary_op(base_url, ctx, i, key):
    """R-1-002, R-1-242: push a payer to, and past, zero so the funds check is
    actually exercised instead of always trivially passing."""
    payer = _pick(ctx, i)
    payee = _pick(ctx, i, offset=1)
    slot = i % 3
    if slot == 0:
        amount = max(1, payer["seed_balance"])        # exactly affordable: may drive the wallet to zero
    elif slot == 1:
        amount = payer["seed_balance"] + 1             # just over: must 409
    else:
        amount = payer["seed_balance"] * 2 + 1          # well over: must 409
    body = {"to_handle": payee["handle"], "amount": amount, "note": f"boundary-{i}"}
    r = _post(base_url, "/payments", json=body, headers={**_auth(payer["token"]), "Idempotency-Key": key})
    return r.status_code


def _auth_create_op(base_url, ctx, i, key):
    payer = _pick(ctx, i)
    receiver = _pick(ctx, i, offset=1)
    amount = 1 + (i % 40)
    body = {"to_handle": receiver["handle"], "amount": amount, "note": f"auth-{i}"}
    r = _post(base_url, "/authorizations", json=body, headers={**_auth(payer["token"]), "Idempotency-Key": key})
    return r.status_code


def _auth_capture_op(base_url, ctx, i, key):
    """R-2-050..066: capture must be driven by the RECEIVER's token, or every
    one of these is a 403 and the slice is vacuous."""
    targets = ctx["seed_auth_targets"]
    if not targets:
        return 404
    target = targets[i % len(targets)]
    receiver = next(u for u in ctx["users"] if u["id"] == target["to_user_id"])
    slot = i % 3
    if slot == 0:
        body = {}  # amount defaults to the remainder, final defaults to true
    elif slot == 1:
        body = {"final": False}
    else:
        body = {"amount": 1, "final": True}
    r = _post(base_url, f"/authorizations/{target['id']}/capture", json=body,
              headers={**_auth(receiver["token"]), "Idempotency-Key": key})
    return r.status_code


def _auth_void_op(base_url, ctx, i, key):
    """R-2-070..075: void must be driven by the PAYER's token, and takes no
    idempotency key."""
    targets = ctx["seed_auth_targets"]
    if not targets:
        return 404
    target = targets[i % len(targets)]
    payer = next(u for u in ctx["users"] if u["id"] == target["from_user_id"])
    r = _post(base_url, f"/authorizations/{target['id']}/void", json={}, headers=_auth(payer["token"]))
    return r.status_code


def operation(base_url: str, ctx: dict, i: int, rng) -> int:
    """A random-but-i-deterministic money-moving call. Same i => same request,
    so calling twice with the same i is a genuine retry (idempotency key is
    derived from i alone)."""
    users = ctx["users"]
    key = f"storm-{i}"

    if i % 19 == 0:
        return _auth_void_op(base_url, ctx, i, key)
    if i % 17 == 0:
        return _auth_capture_op(base_url, ctx, i, key)
    if i % 13 == 0:
        return _auth_create_op(base_url, ctx, i, key)
    if i % 11 == 0:
        return _settlement_boundary_op(base_url, ctx, i, key)
    if i % 7 == 0:
        return _payment_boundary_op(base_url, ctx, i, key)

    kind = i % 5

    if kind == 0:
        # a direct payment
        payer = _pick(ctx, i)
        payee = _pick(ctx, i, offset=1)
        amount = 1 + (i % 50)
        visibility = "public" if i % 2 == 0 else "private"
        body = {"to_handle": payee["handle"], "amount": amount, "note": f"storm-{i}", "visibility": visibility}
        r = _post(base_url, "/payments", json=body, headers={**_auth(payer["token"]), "Idempotency-Key": key})
        return r.status_code

    if kind == 1:
        # create a request then immediately try to pay it (two ops folded into one `i`,
        # but only the create needs the idempotency key for this slot — pay uses its own)
        requester = _pick(ctx, i)
        payer = _pick(ctx, i, offset=2)
        amount = 1 + (i % 30)
        body = {"payer_handle": payer["handle"], "amount": amount, "note": f"req-{i}"}
        r = _post(base_url, "/requests", json=body, headers={**_auth(requester["token"]), "Idempotency-Key": key})
        return r.status_code

    if kind == 2:
        # pay one of the seeded pending requests (bounded set, so repeats contend)
        pending = ctx["pending_requests"]
        if not pending:
            return 404
        req = pending[i % len(pending)]
        payer = next(u for u in users if u["id"] == req["payer_id"])
        r = _post(base_url, f"/requests/{req['id']}/pay", json={},
                  headers={**_auth(payer["token"]), "Idempotency-Key": key})
        if r.status_code == 201:
            with ctx["lock"]:
                ctx["paid_request_ids"].add(req["id"])
        return r.status_code

    if kind == 3:
        # a split among three participants
        caller = _pick(ctx, i)
        p1 = _pick(ctx, i, offset=1)
        p2 = _pick(ctx, i, offset=2)
        amount = 3 + (i % 97)
        body = {"amount": amount, "participant_handles": [caller["handle"], p1["handle"], p2["handle"]],
                "note": f"split-{i}"}
        r = _post(base_url, "/splits", json=body, headers={**_auth(caller["token"]), "Idempotency-Key": key})
        if r.status_code == 201:
            receipt = r.json()
            shares = tuple(s["amount"] for s in receipt["shares"])
            with ctx["lock"]:
                ctx["split_receipts"].append((receipt["amount"], shares))
        return r.status_code

    # kind == 4: a settlement run by the operator
    operator = ctx["operator"]
    a = _pick(ctx, i)
    b = _pick(ctx, i, offset=1)
    amount = 1 + (i % 20)
    body = {"transfers": [{"from_handle": a["handle"], "to_handle": b["handle"], "amount": amount}]}
    r = _post(base_url, "/settlements", json=body, headers={**_auth(operator["token"]), "Idempotency-Key": key})
    return r.status_code


def invariant(base_url: str, ctx: dict) -> tuple[bool, str]:
    total = 0
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]))
        if r.status_code != 200:
            return False, f"GET /me failed for {u['handle']}: {r.status_code} {r.text}"
        body = r.json()
        balance = body["balance"]
        if balance < 0:
            return False, f"negative balance for {u['handle']}: {balance}"
        if body.get("total", balance) != balance:
            return False, f"total != balance for {u['handle']}: {body}"
        held = body.get("held", 0)
        available = body.get("available", balance)
        if held < 0:
            return False, f"negative held for {u['handle']}: {held}"
        if available < 0:
            return False, f"negative available for {u['handle']}: {available}"  # R-2-002
        if available != balance - held:
            return False, f"available != total - held for {u['handle']}: {body}"
        total += balance

        # R-2-004: held must equal the sum of remaining_amount over the
        # caller's own open, unexpired OUTGOING authorizations — never the
        # incoming ones.
        outgoing_open = _get(base_url, "/authorizations", headers=_auth(u["token"]),
                             params={"direction": "outgoing", "status": "open", "limit": 200})
        if outgoing_open.status_code != 200:
            return False, f"GET /authorizations failed for {u['handle']}: {outgoing_open.status_code} {outgoing_open.text}"
        computed_held = sum(a["remaining_amount"] for a in outgoing_open.json()["authorizations"])
        if computed_held != held:
            return False, f"held {held} != sum(remaining_amount over open outgoing) {computed_held} for {u['handle']}"
    if total != ctx["seeded_total"]:
        return False, f"sum of balances {total} != seeded total {ctx['seeded_total']}"

    # R-2-003, R-2-005, R-2-061: per-authorization invariants, checked once
    # per distinct authorization even though it may show up in two users' lists.
    seen_auth_ids: set[str] = set()
    feeds: dict[str, list] = {}
    for u in ctx["users"]:
        r = _get(base_url, "/authorizations", headers=_auth(u["token"]), params={"limit": 200})
        if r.status_code != 200:
            return False, f"GET /authorizations failed for {u['handle']}: {r.status_code} {r.text}"
        for a in r.json()["authorizations"]:
            aid = a["authorization_id"]
            if aid in seen_auth_ids:
                continue
            seen_auth_ids.add(aid)
            if a["captured_amount"] > a["amount"]:
                return False, f"authorization {aid} captured_amount {a['captured_amount']} > amount {a['amount']}"
            if a["status"] != "open" and a["remaining_amount"] != 0:
                return False, f"closed authorization {aid} (status={a['status']}) has nonzero remaining_amount"
            if a["payment_ids"]:
                if u["handle"] not in feeds:
                    feed_resp = _get(base_url, "/activity", headers=_auth(u["token"]), params={"limit": 200})
                    feeds[u["handle"]] = feed_resp.json()["payments"] if feed_resp.status_code == 200 else []
                matched = [p["amount"] for p in feeds[u["handle"]] if p["payment_id"] in a["payment_ids"]]
                if len(matched) == len(a["payment_ids"]) and sum(matched) != a["captured_amount"]:
                    return False, (f"authorization {aid} captured_amount {a['captured_amount']} != "
                                   f"sum of its payment_ids' amounts {sum(matched)}")

    valid_statuses = {"pending", "paid", "declined", "cancelled"}
    # R-1-051: a seeded `paid` request has no seeded payment to link (the fixture
    # format has no field for one), so it legitimately exposes payment_id: null.
    # Only require a non-null payment_id for requests THIS storm paid through
    # POST /requests/{id}/pay — those are genuine API-driven settlements.
    paid_via_api = ctx["paid_request_ids"]
    # payment_id -> set of distinct request_ids that reference it: a single request
    # legitimately shows up once in its requester's list and once in its payer's
    # list (same request_id, counted once here), but one payment must never settle
    # two DIFFERENT requests (R-1-003).
    payment_to_requests: dict[str, set] = {}
    for u in ctx["users"]:
        r = _get(base_url, "/requests", headers=_auth(u["token"]), params={"limit": 200})
        if r.status_code != 200:
            return False, f"GET /requests failed for {u['handle']}: {r.status_code} {r.text}"
        for req in r.json()["requests"]:
            if req["status"] not in valid_statuses:
                return False, f"request {req['request_id']} has invalid status {req['status']}"
            if req["status"] == "paid":
                payment_id = req.get("payment_id")
                if req["request_id"] in paid_via_api and not payment_id:
                    return False, f"request {req['request_id']} was paid via the API but has no payment_id"
                if payment_id:
                    payment_to_requests.setdefault(payment_id, set()).add(req["request_id"])

    for pid, request_ids in payment_to_requests.items():
        if len(request_ids) > 1:
            return False, f"payment_id {pid} settles {len(request_ids)} distinct requests: {sorted(request_ids)}"

    with ctx["lock"]:
        receipts = list(ctx["split_receipts"])
    for amount, shares in receipts:
        if sum(shares) != amount:
            return False, f"split shares {shares} do not sum to amount {amount}"

    return True, "ok"


def _read_wallets(base_url, ctx):
    out = []
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]))
        if r.status_code != 200:
            return None
        out.append(r.json())
    return out


def transient(base_url: str, ctx: dict) -> tuple[bool, str]:
    before = _read_wallets(base_url, ctx)
    if before is None:
        return True, "skip: /me unreachable"
    if any(w["balance"] < 0 for w in before):
        return False, f"negative balance observed mid-storm: {before}"
    if any(w.get("available", w["balance"]) < 0 for w in before):
        return False, f"negative available observed mid-storm: {before}"  # R-2-002
    if any(w.get("available", w["balance"]) > w["balance"] for w in before):
        return False, f"available > total observed mid-storm: {before}"

    after = _read_wallets(base_url, ctx)
    if after is None:
        return True, "skip: /me unreachable"
    if any(w["balance"] < 0 for w in after):
        return False, f"negative balance observed mid-storm: {after}"
    if any(w.get("available", w["balance"]) < 0 for w in after):
        return False, f"negative available observed mid-storm: {after}"
    if any(w.get("available", w["balance"]) > w["balance"] for w in after):
        return False, f"available > total observed mid-storm: {after}"
    return True, "ok"


# ---------------------------------------------------------------------------
# populate / snapshot / carry — required by gate 5 (upgrade/regression)
#
# `populate` runs once against the OLD stage's service and stores everything
# `snapshot` needs — most importantly the pre-upgrade tokens — in `_UPGRADE`,
# a module-level dict. Gate 5 discards `populate`'s return value and calls
# `snapshot(old_url)`, then `carry`, then `snapshot(new_url)` on this SAME
# loaded module instance, so the module-level state set by `populate` is still
# there for both `snapshot` calls (factory/gates/hook.py reloads this file
# fresh for every separate gate invocation, so there is no cross-run leakage).
# ---------------------------------------------------------------------------

_UPGRADE: dict = {}


def populate(base_url: str) -> dict:
    ctx = setup(base_url)
    users = ctx["users"]
    fixture = ctx["fixture"]
    id_to_handle = {u["id"]: u["handle"] for u in users}

    # a completed direct payment, remembered by key+body for the retry-identity check
    payer, payee = users[0], users[1]
    pay_key = "populate-payment-1"
    pay_body = {"to_handle": payee["handle"], "amount": 111, "note": "populate"}
    r = _post(base_url, "/payments", json=pay_body, headers={**_auth(payer["token"]), "Idempotency-Key": pay_key})
    assert r.status_code == 201, r.text

    # a still-pending request
    requester, other_payer = users[2], users[3]
    r = _post(base_url, "/requests", json={"payer_handle": other_payer["handle"], "amount": 222, "note": "populate"},
              headers={**_auth(requester["token"]), "Idempotency-Key": "populate-request-1"})
    assert r.status_code == 201, r.text
    pending_request_id = r.json()["request_id"]

    # a paid split
    caller = users[4]
    p1, p2 = users[5], users[0]
    r = _post(base_url, "/splits", json={"amount": 30, "participant_handles": [caller["handle"], p1["handle"], p2["handle"]]},
              headers={**_auth(caller["token"]), "Idempotency-Key": "populate-split-1"})
    assert r.status_code == 201, r.text
    split = r.json()
    split_request_ids = []
    for req in split["requests"]:
        rp = next(u for u in users if u["handle"] == req["payer_handle"])
        pr = _post(base_url, f"/requests/{req['request_id']}/pay", json={},
                   headers={**_auth(rp["token"]), "Idempotency-Key": f"populate-pay-{req['request_id']}"})
        assert pr.status_code == 201, pr.text
        split_request_ids.append(req["request_id"])

    # a committed settlement
    operator = ctx["operator"]
    a, b = users[0], users[1]
    r = _post(base_url, "/settlements", json={"transfers": [{"from_handle": a["handle"], "to_handle": b["handle"], "amount": 10}]},
              headers={**_auth(operator["token"]), "Idempotency-Key": "populate-settlement-1"})
    assert r.status_code == 201, r.text
    settlement_id = r.json()["settlement_id"]

    # every known request we can check the state of after an upgrade: the seeded
    # ones (fixed ids from demo_fixture) plus the ones created just above.
    known_requests = [(req["id"], id_to_handle[req["requester_id"]]) for req in fixture["requests"]]
    known_requests.append((pending_request_id, requester["handle"]))
    known_requests += [(rid, caller["handle"]) for rid in split_request_ids]

    # an open hold
    auth_payer, auth_receiver = users[2], users[4]
    r = _post(base_url, "/authorizations", json={"to_handle": auth_receiver["handle"], "amount": 200,
                                                   "note": "populate-open"},
              headers={**_auth(auth_payer["token"]), "Idempotency-Key": "populate-auth-open-1"})
    assert r.status_code == 201, r.text
    open_auth_id = r.json()["authorization_id"]

    # a partially captured hold (final: false), with a claimed capture key remembered
    part_payer, part_receiver = users[3], users[5]
    r = _post(base_url, "/authorizations", json={"to_handle": part_receiver["handle"], "amount": 400,
                                                   "note": "populate-partial"},
              headers={**_auth(part_payer["token"]), "Idempotency-Key": "populate-auth-partial-1"})
    assert r.status_code == 201, r.text
    partial_auth_id = r.json()["authorization_id"]
    capture_key = "populate-capture-partial-1"
    capture_body = {"amount": 150, "final": False}
    cap = _post(base_url, f"/authorizations/{partial_auth_id}/capture", json=capture_body,
                headers={**_auth(part_receiver["token"]), "Idempotency-Key": capture_key})
    assert cap.status_code == 201, cap.text

    # a voided hold
    void_payer, void_receiver = users[4], users[0]
    r = _post(base_url, "/authorizations", json={"to_handle": void_receiver["handle"], "amount": 90,
                                                   "note": "populate-void"},
              headers={**_auth(void_payer["token"]), "Idempotency-Key": "populate-auth-void-1"})
    assert r.status_code == 201, r.text
    void_auth_id = r.json()["authorization_id"]
    voided = _post(base_url, f"/authorizations/{void_auth_id}/void", json={}, headers=_auth(void_payer["token"]))
    assert voided.status_code == 200, voided.text

    known_authorizations = [(a["id"], id_to_handle[a["from_user_id"]]) for a in fixture.get("authorizations", [])]
    known_authorizations += [
        (open_auth_id, auth_payer["handle"]),
        (partial_auth_id, part_payer["handle"]),
        (void_auth_id, void_payer["handle"]),
    ]

    _UPGRADE.clear()
    _UPGRADE.update({
        "tokens": {u["handle"]: u["token"] for u in users},
        "known_requests": known_requests,
        "known_authorizations": known_authorizations,
        "settlement_id": settlement_id,
        "settlement_participant_handle": a["handle"],
        "remembered_key": pay_key,
        "remembered_body": pay_body,
        "remembered_payer_handle": payer["handle"],
        "remembered_capture_key": capture_key,
        "remembered_capture_body": capture_body,
        "remembered_capture_authorization_id": partial_auth_id,
        "remembered_capture_receiver_handle": part_receiver["handle"],
    })
    return {"ctx": ctx, "settlement_id": settlement_id, "pending_request_id": pending_request_id}


def snapshot(base_url: str) -> dict:
    """A semantic fingerprint re-derived from the service at `base_url`,
    containing only facts that must be identical before and after ANY correct
    upgrade — never a raw version-specific document like `/_test/export`."""
    assert _UPGRADE, "populate() must run before snapshot()"
    tokens = _UPGRADE["tokens"]

    balances = {}
    identities = {}
    wallets = {}
    for handle in sorted(tokens):
        token = tokens[handle]
        r = _get(base_url, "/me", headers=_auth(token))
        assert r.status_code == 200, f"pre-upgrade token for {handle} stopped authenticating: {r.status_code} {r.text}"
        body = r.json()
        balances[handle] = body["balance"]
        identities[handle] = (body["user_id"], body["handle"])
        wallets[handle] = (body["balance"], body.get("held", 0), body.get("available", body["balance"]))

    requests_state = []
    for req_id, viewer_handle in sorted(set(_UPGRADE["known_requests"])):
        token = tokens[viewer_handle]
        r = _get(base_url, "/requests", headers=_auth(token), params={"limit": 200})
        assert r.status_code == 200, f"GET /requests failed for {viewer_handle}: {r.status_code} {r.text}"
        match = next((x for x in r.json()["requests"] if x["request_id"] == req_id), None)
        assert match is not None, f"known request {req_id} is no longer visible to {viewer_handle}"
        requests_state.append((req_id, match["status"], match["payment_id"]))
    requests_state.sort()

    settlement_token = tokens[_UPGRADE["settlement_participant_handle"]]
    feed = _get(base_url, "/activity", headers=_auth(settlement_token), params={"limit": 200})
    assert feed.status_code == 200, feed.text
    settlement_members = sorted(
        (p["payment_id"], p["amount"]) for p in feed.json()["payments"]
        if p.get("settlement_id") == _UPGRADE["settlement_id"]
    )

    replay_token = tokens[_UPGRADE["remembered_payer_handle"]]
    replay = _post(base_url, "/payments", json=_UPGRADE["remembered_body"],
                   headers={**_auth(replay_token), "Idempotency-Key": _UPGRADE["remembered_key"]})
    assert replay.status_code == 200, \
        f"replay of the remembered payment must stay a 200 replay: {replay.status_code} {replay.text}"

    auth_state = []
    for auth_id, viewer_handle in sorted(set(_UPGRADE["known_authorizations"])):
        token = tokens[viewer_handle]
        r = _get(base_url, "/authorizations", headers=_auth(token), params={"limit": 200})
        assert r.status_code == 200, f"GET /authorizations failed for {viewer_handle}: {r.status_code} {r.text}"
        match = next((x for x in r.json()["authorizations"] if x["authorization_id"] == auth_id), None)
        assert match is not None, f"known authorization {auth_id} is no longer visible to {viewer_handle}"
        auth_state.append((auth_id, match["status"], match["captured_amount"], match["remaining_amount"],
                            tuple(match["payment_ids"]), match["closed_at"]))
    auth_state.sort()

    capture_replay_token = tokens[_UPGRADE["remembered_capture_receiver_handle"]]
    capture_replay = _post(
        base_url, f"/authorizations/{_UPGRADE['remembered_capture_authorization_id']}/capture",
        json=_UPGRADE["remembered_capture_body"],
        headers={**_auth(capture_replay_token), "Idempotency-Key": _UPGRADE["remembered_capture_key"]})
    assert capture_replay.status_code == 200, \
        f"replay of the remembered capture must stay a 200 replay: {capture_replay.status_code} {capture_replay.text}"

    return {
        "balances": balances,
        "identities": identities,
        "wallets": wallets,
        "requests": requests_state,
        "authorizations": auth_state,
        "settlement_id": _UPGRADE["settlement_id"],
        "settlement_members": settlement_members,
        "retry_identity": (replay.status_code, replay.json()),
        "capture_retry_identity": (capture_replay.status_code, capture_replay.json()),
    }


def carry(old_url: str, new_url: str) -> None:
    export = _get(old_url, "/_test/export")
    assert export.status_code == 200, export.text
    document = export.json()
    r = _post(new_url, "/_test/import", json=document)
    assert r.status_code == 204, r.text


# ---------------------------------------------------------------------------
# UI_ROUTES / ui_login — required by gate 7, load-bearing from stage 2 on
# ---------------------------------------------------------------------------

UI_ROUTES = ["/", "/requests", "/split", "/signup", "/login", "/authorizations"]


def ui_login(page, base_url: str) -> None:
    """Reset to the demo fixture (so every route has real content per
    R-2-111) and sign the primary demo user (alice) in through the actual
    login form, by its data-testid contract (R-2-121), so gate 7 sees real
    screens rather than a login wall on every one of UI_ROUTES."""
    fixture = build_demo_fixture()
    r = httpx.post(base_url.rstrip("/") + "/_test/reset", json=fixture, timeout=TIMEOUT)
    assert r.status_code == 204, f"reset failed: {r.status_code} {r.text}"
    primary = fixture["users"][0]
    page.goto(base_url.rstrip("/") + "/login", wait_until="load")
    page.fill('[data-testid="login-email"]', primary["email"])
    page.fill('[data-testid="login-password"]', primary["password"])
    page.click('[data-testid="login-submit"]')
    page.wait_for_load_state("load")
