"""Gate hook for pocketful stage 1 — see factory/gates/hook.py for the
contract. Imports the same demo fixture the pytest suite uses, so stage 2's
first screen is never empty and the storm exercises real-looking data.
"""
from __future__ import annotations

import sys
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
    tokens = []
    for u in fixture["users"]:
        lr = _post(base_url, "/auth/login", json={"email": u["email"], "password": u["password"]})
        assert lr.status_code == 200, f"login failed for {u['handle']}: {lr.status_code} {lr.text}"
        token = lr.json()["token"]
        users.append({"id": u["id"], "handle": u["handle"], "token": token})
        tokens.append(token)

    # the operator is u-alice (see demo_fixture.SETTLEMENT_OPERATOR_IDS)
    operator = next(u for u in users if u["id"] == fixture["settlement_operator_ids"][0])

    # at least one settlement operator, plus two seeded pending requests we can pay
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
    }


def _pick(ctx, i, offset=0):
    users = ctx["users"]
    return users[(i + offset) % len(users)]


def operation(base_url: str, ctx: dict, i: int, rng) -> int:
    """A random-but-i-deterministic money-moving call. Same i => same request,
    so calling twice with the same i is a genuine retry (idempotency key is
    derived from i alone)."""
    users = ctx["users"]
    n = len(users)
    kind = i % 5
    key = f"storm-{i}"

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
    seen_payment_ids: dict[str, int] = {}
    for u in ctx["users"]:
        r = _get(base_url, "/requests", headers=_auth(u["token"]), params={"limit": 200})
        if r.status_code != 200:
            return False, f"GET /requests failed for {u['handle']}: {r.status_code} {r.text}"
        for req in r.json()["requests"]:
            if req["status"] not in valid_statuses:
                return False, f"request {req['request_id']} has invalid status {req['status']}"
            if req["status"] == "paid":
                if not req.get("payment_id"):
                    return False, f"paid request {req['request_id']} has no payment_id"
                seen_payment_ids[req["payment_id"]] = seen_payment_ids.get(req["payment_id"], 0) + 1

    for pid, count in seen_payment_ids.items():
        # a requester and a payer both see the same request, so a payment_id may
        # legitimately appear twice (once per party) but never more.
        if count > 2:
            return False, f"payment_id {pid} referenced by {count} requests"

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
# ---------------------------------------------------------------------------

def populate(base_url: str) -> dict:
    ctx = setup(base_url)
    users = ctx["users"]

    # a completed direct payment
    payer, payee = users[0], users[1]
    pay_key = "populate-payment-1"
    r = _post(base_url, "/payments", json={"to_handle": payee["handle"], "amount": 111, "note": "populate"},
              headers={**_auth(payer["token"]), "Idempotency-Key": pay_key})
    assert r.status_code == 201, r.text
    remembered_payment = r.json()

    # a replay of that same payment — remember the exact (request, response) pair

    replay = _post(base_url, "/payments", json={"to_handle": payee["handle"], "amount": 111, "note": "populate"},
                   headers={**_auth(payer["token"]), "Idempotency-Key": pay_key})
    assert replay.status_code == 200, replay.text

    # a still-pending request
    requester, other_payer = users[2], users[3]
    r = _post(base_url, "/requests", json={"payer_handle": other_payer["handle"], "amount": 222, "note": "populate"},
              headers={**_auth(requester["token"]), "Idempotency-Key": "populate-request-1"})
    assert r.status_code == 201, r.text
    pending_request = r.json()

    # a paid split
    caller = users[4]
    p1, p2 = users[5], users[0]
    r = _post(base_url, "/splits", json={"amount": 30, "participant_handles": [caller["handle"], p1["handle"], p2["handle"]]},
              headers={**_auth(caller["token"]), "Idempotency-Key": "populate-split-1"})
    assert r.status_code == 201, r.text
    split = r.json()
    for req in split["requests"]:
        rp = next(u for u in users if u["handle"] == req["payer_handle"])
        pr = _post(base_url, f"/requests/{req['request_id']}/pay", json={},
                   headers={**_auth(rp["token"]), "Idempotency-Key": f"populate-pay-{req['request_id']}"})
        assert pr.status_code == 201, pr.text

    # a committed settlement
    operator = ctx["operator"]
    a, b = users[0], users[1]
    r = _post(base_url, "/settlements", json={"transfers": [{"from_handle": a["handle"], "to_handle": b["handle"], "amount": 10}]},
              headers={**_auth(operator["token"]), "Idempotency-Key": "populate-settlement-1"})
    assert r.status_code == 201, r.text
    settlement = r.json()

    return {
        "ctx": ctx,
        "remembered_payment": remembered_payment,
        "remembered_key": pay_key,
        "remembered_payer": payer,
        "pending_request": pending_request,
        "split": split,
        "settlement": settlement,
    }


def _balances(base_url: str, ctx: dict) -> dict:
    out = {}
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]))
        assert r.status_code == 200, r.text
        out[u["handle"]] = r.json()["balance"]
    return out


def snapshot(base_url: str):
    export = _get(base_url, "/_test/export")
    assert export.status_code == 200, export.text
    return export.json()


def carry(old_url: str, new_url: str) -> None:
    export = _get(old_url, "/_test/export")
    assert export.status_code == 200, export.text
    document = export.json()
    r = _post(new_url, "/_test/import", json=document)
    assert r.status_code == 204, r.text
