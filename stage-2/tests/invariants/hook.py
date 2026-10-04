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

    return {
        "fixture": fixture,
        "users": users,
        "operator": operator,
        "seeded_total": sum(u["balance"] for u in fixture["users"]),
        "pending_requests": pending_requests,
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


def operation(base_url: str, ctx: dict, i: int, rng) -> int:
    """A random-but-i-deterministic money-moving call. Same i => same request,
    so calling twice with the same i is a genuine retry (idempotency key is
    derived from i alone)."""
    users = ctx["users"]
    key = f"storm-{i}"

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
        balance = r.json()["balance"]
        if balance < 0:
            return False, f"negative balance for {u['handle']}: {balance}"
        total += balance
    if total != ctx["seeded_total"]:
        return False, f"sum of balances {total} != seeded total {ctx['seeded_total']}"

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


def transient(base_url: str, ctx: dict) -> tuple[bool, str]:
    before = []
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]))
        if r.status_code != 200:
            return True, "skip: /me unreachable"
        before.append(r.json()["balance"])
    if any(b < 0 for b in before):
        return False, f"negative balance observed mid-storm: {before}"

    after = []
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]))
        if r.status_code != 200:
            return True, "skip: /me unreachable"
        after.append(r.json()["balance"])
    if any(b < 0 for b in after):
        return False, f"negative balance observed mid-storm: {after}"
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

    _UPGRADE.clear()
    _UPGRADE.update({
        "tokens": {u["handle"]: u["token"] for u in users},
        "known_requests": known_requests,
        "settlement_id": settlement_id,
        "settlement_participant_handle": a["handle"],
        "remembered_key": pay_key,
        "remembered_body": pay_body,
        "remembered_payer_handle": payer["handle"],
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
    for handle in sorted(tokens):
        token = tokens[handle]
        r = _get(base_url, "/me", headers=_auth(token))
        assert r.status_code == 200, f"pre-upgrade token for {handle} stopped authenticating: {r.status_code} {r.text}"
        body = r.json()
        balances[handle] = body["balance"]
        identities[handle] = (body["user_id"], body["handle"])

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

    return {
        "balances": balances,
        "identities": identities,
        "requests": requests_state,
        "settlement_id": _UPGRADE["settlement_id"],
        "settlement_members": settlement_members,
        "retry_identity": (replay.status_code, replay.json()),
    }


def carry(old_url: str, new_url: str) -> None:
    export = _get(old_url, "/_test/export")
    assert export.status_code == 200, export.text
    document = export.json()
    r = _post(new_url, "/_test/import", json=document)
    assert r.status_code == 204, r.text
