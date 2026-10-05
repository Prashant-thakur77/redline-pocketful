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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from demo_fixture import build_demo_fixture, opening_balances  # noqa: E402

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

    now = datetime.now(timezone.utc)
    id_to_handle = {u["id"]: u["handle"] for u in users}
    correction_targets = [
        {"id": p["id"], "from_user_id": p["from_user_id"]} for p in fixture["payments"]
    ]

    # R-3-005: a statement snapshot token taken before the storm starts must
    # page identically after the storm has run (frozen pagination). Captured
    # best-effort: a 404/other here just means this stage's statement
    # endpoint isn't implemented yet, so the check is skipped in invariant().
    statement_snapshot_token = None
    statement_first_page = None
    primary = users[0]
    init = _get(base_url, "/statement", headers=_auth(primary["token"]), params={"limit": 5})
    if init.status_code == 200:
        body = init.json()
        statement_snapshot_token = body.get("snapshot_token")
        statement_first_page = body

    return {
        "fixture": fixture,
        "users": users,
        "operator": operator,
        "seeded_total": sum(u["balance"] for u in fixture["users"]),
        "opening_balances": opening_balances(),
        "id_to_handle": id_to_handle,
        "now": now,
        "pending_requests": pending_requests,
        "seed_auth_targets": seed_auth_targets,
        "correction_targets": correction_targets,
        "statement_snapshot_user": primary["handle"],
        "statement_snapshot_token": statement_snapshot_token,
        "statement_first_page": statement_first_page,
        "n": len(users),
        "lock": threading.Lock(),
        "split_receipts": [],
        "paid_request_ids": set(),
        "applied_corrections": [],
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


def _correction_op(base_url, ctx, i, key):
    """R-3-050..069: a payment correction, i-deterministic in every field so
    a repeated `i` is a genuine idempotent retry. `expected_revision` cycles
    so some calls land on the true current revision (success) and most are
    deliberately stale (409 stale_revision) under storm concurrency.
    `effective_at` is sometimes pushed before the payment's own creation to
    exercise historical-overdraft/ordering paths (R-3-059, R-3-060), not just
    corrections that land after everything else."""
    targets = ctx["correction_targets"]
    if not targets:
        return 404
    target = targets[i % len(targets)]
    payer = next((u for u in ctx["users"] if u["id"] == target["from_user_id"]), None)
    if payer is None:
        return 404
    expected_revision = 1 + ((i // max(1, len(targets))) % 3)
    amount = i % 50  # include 0: a zero-amount correction is a legal distinct case
    offset_days = (i % 9) - 4  # ranges negative (historical) through positive (future-dated)
    effective_at = (ctx["now"] + timedelta(days=offset_days, seconds=i)).isoformat()
    body = {"expected_revision": expected_revision, "amount": amount,
            "effective_at": effective_at, "reason": f"storm-correction-{i}"}
    r = _post(base_url, f"/payments/{target['id']}/corrections", json=body,
              headers={**_auth(payer["token"]), "Idempotency-Key": key})
    if r.status_code == 201:
        with ctx["lock"]:
            ctx["applied_corrections"].append({"payment_id": target["id"], "response": r.json()})
    return r.status_code


def _statement_read_op(base_url, ctx, i):
    """R-3-030..044: exercise GET /statement under storm load."""
    user = _pick(ctx, i)
    r = _get(base_url, "/statement", headers=_auth(user["token"]), params={"limit": 20})
    return r.status_code


def _me_as_of_known_at_op(base_url, ctx, i):
    """R-3-020..027, R-3-070..077: exercise the bitemporal query params on
    GET /me under storm load — some instants land before the earliest
    seeded payment, some in the middle, some in the future."""
    user = _pick(ctx, i)
    as_of = (ctx["now"] + timedelta(hours=(i % 96) - 72)).isoformat()
    known_at = (ctx["now"] + timedelta(hours=(i % 60) - 48)).isoformat()
    r = _get(base_url, "/me", headers=_auth(user["token"]), params={"as_of": as_of, "known_at": known_at})
    return r.status_code


def operation(base_url: str, ctx: dict, i: int, rng) -> int:
    """A random-but-i-deterministic money-moving call. Same i => same request,
    so calling twice with the same i is a genuine retry (idempotency key is
    derived from i alone)."""
    users = ctx["users"]
    key = f"storm-{i}"

    if i % 29 == 0:
        return _statement_read_op(base_url, ctx, i)
    if i % 31 == 0:
        return _me_as_of_known_at_op(base_url, ctx, i)
    if i % 23 == 0:
        return _correction_op(base_url, ctx, i, key)
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

    # R-3-001, R-3-002: a bitemporal view (as_of + known_at together) must
    # still conserve total money and never show a negative balance — a
    # correction moves money between two accounts, it never mints or burns.
    # A 404 here means this stage's endpoint doesn't support the params yet
    # (skip, not fail); any other non-200 is a real defect.
    as_of = ctx["now"].isoformat()
    known_at = ctx["now"].isoformat()
    bitemporal_total = 0
    bitemporal_supported = True
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]), params={"as_of": as_of, "known_at": known_at})
        if r.status_code == 404:
            bitemporal_supported = False
            break
        if r.status_code != 200:
            return False, f"GET /me?as_of&known_at failed for {u['handle']}: {r.status_code} {r.text}"
        bal = r.json()["balance"]
        if bal < 0:
            return False, f"negative bitemporal balance for {u['handle']} at as_of={as_of}: {bal}"
        bitemporal_total += bal
    if bitemporal_supported and bitemporal_total != ctx["seeded_total"]:
        return False, (f"sum of bitemporal balances {bitemporal_total} at as_of={as_of} "
                        f"!= seeded total {ctx['seeded_total']}")

    # R-3-016: an as_of strictly before the earliest seeded payment must show
    # each user's pre-payment opening balance, not their current one.
    before_earliest = (ctx["now"] - timedelta(days=2, seconds=1)).isoformat()
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]), params={"as_of": before_earliest})
        if r.status_code == 404:
            break
        if r.status_code != 200:
            return False, f"GET /me?as_of (pre-earliest) failed for {u['handle']}: {r.status_code} {r.text}"
        expected = ctx["opening_balances"].get(u["id"])
        if expected is not None and r.json()["balance"] != expected:
            return False, (f"as_of={before_earliest} (before any seeded payment) balance for "
                            f"{u['handle']} is {r.json()['balance']}, expected opening balance {expected}")

    # R-3-003, R-3-004: every corrected payment's revision history must start
    # at revision 1 (reason ""), be consecutive, and have strictly increasing
    # recorded_at.
    with ctx["lock"]:
        corrected_ids = sorted({c["payment_id"] for c in ctx["applied_corrections"]})
    for payment_id in corrected_ids:
        token = ctx["users"][0]["token"]
        r = _get(base_url, f"/payments/{payment_id}/revisions", headers=_auth(token))
        if r.status_code == 404:
            continue
        if r.status_code != 200:
            return False, f"GET /payments/{payment_id}/revisions failed: {r.status_code} {r.text}"
        revisions = sorted(r.json().get("revisions", r.json() if isinstance(r.json(), list) else []),
                            key=lambda rv: rv["revision"])
        if not revisions or revisions[0]["revision"] != 1:
            return False, f"payment {payment_id} revision history does not start at revision 1: {revisions}"
        if revisions[0].get("reason", "") != "":
            return False, f"payment {payment_id} revision 1 must have reason '': {revisions[0]}"
        for a, b in zip(revisions, revisions[1:]):
            if b["revision"] != a["revision"] + 1:
                return False, f"payment {payment_id} revisions are not consecutive: {revisions}"
            if b["recorded_at"] <= a["recorded_at"]:
                return False, f"payment {payment_id} revision recorded_at is not strictly increasing: {revisions}"

    # R-3-005: a snapshot token taken before the storm started must page
    # identically after the storm has run (frozen pagination), regardless of
    # how many corrections/payments have since been recorded.
    if ctx.get("statement_snapshot_token"):
        token = next(u["token"] for u in ctx["users"] if u["handle"] == ctx["statement_snapshot_user"])
        r = _get(base_url, "/statement", headers=_auth(token),
                 params={"limit": 5, "snapshot_token": ctx["statement_snapshot_token"]})
        if r.status_code == 200 and r.json() != ctx["statement_first_page"]:
            return False, (f"statement page re-fetched with the pre-storm snapshot_token changed: "
                            f"before={ctx['statement_first_page']} after={r.json()}")

    return True, "ok"


def _read_wallets(base_url, ctx):
    out = []
    for u in ctx["users"]:
        r = _get(base_url, "/me", headers=_auth(u["token"]))
        if r.status_code != 200:
            return None
        out.append(r.json())
    return out


def _read_historical_bound(base_url, ctx):
    """R-3-002: a client-side bound taken from a single as_of read mid-storm —
    never a torn snapshot assembled across multiple reads."""
    user = ctx["users"][0]
    r = _get(base_url, "/me", headers=_auth(user["token"]),
             params={"as_of": ctx["now"].isoformat()})
    if r.status_code != 200:
        return None
    return r.json()["balance"]


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
    historical_before = _read_historical_bound(base_url, ctx)
    if historical_before is not None and historical_before < 0:
        return False, f"negative as_of balance observed mid-storm: {historical_before}"

    after = _read_wallets(base_url, ctx)
    if after is None:
        return True, "skip: /me unreachable"
    if any(w["balance"] < 0 for w in after):
        return False, f"negative balance observed mid-storm: {after}"
    if any(w.get("available", w["balance"]) < 0 for w in after):
        return False, f"negative available observed mid-storm: {after}"
    if any(w.get("available", w["balance"]) > w["balance"] for w in after):
        return False, f"available > total observed mid-storm: {after}"
    historical_after = _read_historical_bound(base_url, ctx)
    if historical_after is not None and historical_after < 0:
        return False, f"negative as_of balance observed mid-storm: {historical_after}"
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

    # Capability probe, run ONCE here and recorded in _UPGRADE["holds"] for
    # BOTH snapshot() calls to branch on — never re-probed per-url, since
    # gate 5's upgrade() runs populate() and the first snapshot() against the
    # OLD stage's binary and only the second snapshot() against the new one
    # (factory/gates/g5_regression.py:22-37). If each side probed its own
    # url, a stage-1 (no holds) vs stage-2 (holds) fingerprint would differ
    # in SHAPE and before == after could never hold, even for a correct
    # upgrade. One flag, recorded once, used twice.
    probe = _get(base_url, "/authorizations", headers=_auth(users[0]["token"]))
    supports_holds = probe.status_code == 200
    assert probe.status_code in (200, 404), f"unexpected probe status: {probe.status_code} {probe.text}"

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
        "holds": supports_holds,
        "populated_url": base_url,
        "tokens": {u["handle"]: u["token"] for u in users},
        "known_requests": known_requests,
        "known_authorizations": [],
        "settlement_id": settlement_id,
        "settlement_participant_handle": a["handle"],
        "remembered_key": pay_key,
        "remembered_body": pay_body,
        "remembered_payer_handle": payer["handle"],
        "remembered_capture_key": None,
        "remembered_capture_body": None,
        "remembered_capture_authorization_id": None,
        "remembered_capture_receiver_handle": None,
    })

    if supports_holds:
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

        _UPGRADE["known_authorizations"] = known_authorizations
        _UPGRADE["remembered_capture_key"] = capture_key
        _UPGRADE["remembered_capture_body"] = capture_body
        _UPGRADE["remembered_capture_authorization_id"] = partial_auth_id
        _UPGRADE["remembered_capture_receiver_handle"] = part_receiver["handle"]

    # Capability probe for stage 3's bitemporal/corrections surface, same
    # one-probe-used-twice discipline as supports_holds above.
    corrections_probe = _get(base_url, "/statement", headers=_auth(users[0]["token"]))
    supports_corrections = corrections_probe.status_code == 200
    assert corrections_probe.status_code in (200, 404), \
        f"unexpected probe status: {corrections_probe.status_code} {corrections_probe.text}"

    _UPGRADE["supports_corrections"] = supports_corrections
    _UPGRADE["known_correction_payment_ids"] = []
    _UPGRADE["remembered_correction_key"] = None
    _UPGRADE["remembered_correction_body"] = None
    _UPGRADE["remembered_correction_payment_id"] = None
    _UPGRADE["remembered_correction_caller_handle"] = None
    _UPGRADE["statement_snapshot_handle"] = None
    _UPGRADE["statement_snapshot_token"] = None
    _UPGRADE["statement_first_page"] = None

    if supports_corrections:
        # two applied corrections against the seeded payments: one increase,
        # one decrease (R-3-050..069) — both must land on revision 1, the
        # implicit original revision every payment, including a seeded one,
        # must already have.
        seeded_payer_1 = next(u for u in users if u["id"] == fixture["payments"][0]["from_user_id"])
        seeded_payment_1_id = fixture["payments"][0]["id"]
        inc = _post(base_url, f"/payments/{seeded_payment_1_id}/corrections",
                    json={"expected_revision": 1, "amount": fixture["payments"][0]["amount"] + 100,
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "populate-increase"},
                    headers={**_auth(seeded_payer_1["token"]), "Idempotency-Key": "populate-correction-increase-1"})
        assert inc.status_code == 201, inc.text

        seeded_payer_2 = next(u for u in users if u["id"] == fixture["payments"][1]["from_user_id"])
        seeded_payment_2_id = fixture["payments"][1]["id"]
        dec = _post(base_url, f"/payments/{seeded_payment_2_id}/corrections",
                    json={"expected_revision": 1, "amount": max(1, fixture["payments"][1]["amount"] - 100),
                          "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "populate-decrease"},
                    headers={**_auth(seeded_payer_2["token"]), "Idempotency-Key": "populate-correction-decrease-1"})
        assert dec.status_code == 201, dec.text

        # a zero-amount correction on a freshly made payment — a distinct
        # legal case from a decrease, remembered for the post-import retry
        # idempotency check below.
        zero_payer, zero_payee = users[4], users[5]
        zero_pay = _post(base_url, "/payments",
                          json={"to_handle": zero_payee["handle"], "amount": 50, "note": "pre-zero-correction"},
                          headers={**_auth(zero_payer["token"]), "Idempotency-Key": "populate-payment-for-zero-correction"})
        assert zero_pay.status_code == 201, zero_pay.text
        zero_payment_id = zero_pay.json()["payment_id"]
        correction_key = "populate-correction-zero-1"
        correction_body = {"expected_revision": 1, "amount": 0,
                            "effective_at": datetime.now(timezone.utc).isoformat(), "reason": "populate-zero"}
        zero_corr = _post(base_url, f"/payments/{zero_payment_id}/corrections", json=correction_body,
                           headers={**_auth(zero_payer["token"]), "Idempotency-Key": correction_key})
        assert zero_corr.status_code == 201, zero_corr.text

        _UPGRADE["known_correction_payment_ids"] = [seeded_payment_1_id, seeded_payment_2_id, zero_payment_id]
        _UPGRADE["remembered_correction_key"] = correction_key
        _UPGRADE["remembered_correction_body"] = correction_body
        _UPGRADE["remembered_correction_payment_id"] = zero_payment_id
        _UPGRADE["remembered_correction_caller_handle"] = zero_payer["handle"]

        snap = _get(base_url, "/statement", headers=_auth(users[0]["token"]), params={"limit": 5})
        if snap.status_code == 200:
            snap_body = snap.json()
            _UPGRADE["statement_snapshot_handle"] = users[0]["handle"]
            _UPGRADE["statement_snapshot_token"] = snap_body.get("snapshot_token")
            _UPGRADE["statement_first_page"] = snap_body

    return {"ctx": ctx, "settlement_id": settlement_id, "pending_request_id": pending_request_id,
            "supports_holds": supports_holds, "supports_corrections": supports_corrections}


def snapshot(base_url: str) -> dict:
    """A semantic fingerprint re-derived from the service at `base_url`,
    containing only facts that must be identical before and after ANY correct
    upgrade — never a raw version-specific document like `/_test/export`."""
    assert _UPGRADE, "populate() must run before snapshot()"
    tokens = _UPGRADE["tokens"]

    balances = {}
    identities = {}
    wallets = {}
    sample_me_body = None
    for handle in sorted(tokens):
        token = tokens[handle]
        r = _get(base_url, "/me", headers=_auth(token))
        assert r.status_code == 200, f"pre-upgrade token for {handle} stopped authenticating: {r.status_code} {r.text}"
        body = r.json()
        sample_me_body = body
        balances[handle] = body["balance"]
        identities[handle] = (body["user_id"], body["handle"])
        # .get(..., default) is deliberate ONLY for tolerating the OLD side
        # (stage 1 never had these fields); the new-side liveness guard below
        # is what stops this same default from also masking a NEW-side
        # regression where stage 2 stopped returning them.
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

    # Branch on the ONE flag populate() recorded — never re-probe this url,
    # or a stage-1 (no holds) vs stage-2 (holds) fingerprint would differ in
    # shape and before == after could never hold for a correct upgrade.
    # known_authorizations/remembered_capture_key are already [] / None when
    # holds is False, so the loop and the replay below degrade to no-ops on
    # their own — but that silence is exactly the danger: if a REGRESSION
    # ever made the NEW service start 404-ing GET /authorizations, this same
    # silent degradation would hide it instead of failing gate 5. So on the
    # side that is NOT the one populate() ran on (i.e. the new, upgraded
    # side), assert the endpoint is alive even though nothing is fingerprinted
    # from it — a downgrade is then loud, never silent.
    if not _UPGRADE["holds"] and base_url != _UPGRADE["populated_url"]:
        token = next(iter(tokens.values()))
        liveness = _get(base_url, "/authorizations", headers=_auth(token))
        assert liveness.status_code == 200, (
            "new-side service must still expose holds even when the old side had none: "
            f"GET /authorizations returned {liveness.status_code} {liveness.text}, which would "
            "be a silent regression if not checked here")
        # The same silent-default hazard applies to GET /me: wallets{} above
        # tolerates a MISSING held/available via .get(..., default), which is
        # correct for the old (stage-1) side but would also mask a new-side
        # regression where stage 2 stopped returning them. R-2-010 makes both
        # mandatory on this stage, so check PRESENCE, not just a safe value.
        assert sample_me_body is not None and "held" in sample_me_body and "available" in sample_me_body, (
            "new-side service must still expose holds even when the old side had none: "
            f"GET /me is missing 'held' and/or 'available' ({sample_me_body}), which would "
            "be a silent regression if not checked here")

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

    capture_retry_identity = None
    if _UPGRADE.get("remembered_capture_key"):
        capture_replay_token = tokens[_UPGRADE["remembered_capture_receiver_handle"]]
        capture_replay = _post(
            base_url, f"/authorizations/{_UPGRADE['remembered_capture_authorization_id']}/capture",
            json=_UPGRADE["remembered_capture_body"],
            headers={**_auth(capture_replay_token), "Idempotency-Key": _UPGRADE["remembered_capture_key"]})
        assert capture_replay.status_code == 200, \
            f"replay of the remembered capture must stay a 200 replay: {capture_replay.status_code} {capture_replay.text}"
        capture_retry_identity = (capture_replay.status_code, capture_replay.json())

    # Same anti-silent-downgrade discipline as the holds guard above, for
    # stage 3's corrections/statement surface: if the OLD side had none
    # (this probe only ran once, in populate(), against populated_url), the
    # NEW side must still have it — a regression there must be loud, never
    # masked by corrections/statement fields simply being absent/empty.
    if not _UPGRADE["supports_corrections"] and base_url != _UPGRADE["populated_url"]:
        token = next(iter(tokens.values()))
        liveness = _get(base_url, "/statement", headers=_auth(token))
        assert liveness.status_code == 200, (
            "new-side service must still expose statements/corrections even when the old "
            f"side had none: GET /statement returned {liveness.status_code} {liveness.text}, "
            "which would be a silent regression if not checked here")

    revision_state = []
    for payment_id in sorted(set(_UPGRADE["known_correction_payment_ids"])):
        token = next(iter(tokens.values()))
        r = _get(base_url, f"/payments/{payment_id}/revisions", headers=_auth(token))
        assert r.status_code == 200, f"known corrected payment {payment_id} lost its revision history: " \
                                      f"{r.status_code} {r.text}"
        revisions = r.json().get("revisions", r.json() if isinstance(r.json(), list) else [])
        revision_state.append((payment_id, tuple(sorted((rv["revision"], rv["amount"]) for rv in revisions))))
    revision_state.sort()

    correction_retry_identity = None
    if _UPGRADE.get("remembered_correction_key"):
        correction_replay_token = tokens[_UPGRADE["remembered_correction_caller_handle"]]
        correction_replay = _post(
            base_url, f"/payments/{_UPGRADE['remembered_correction_payment_id']}/corrections",
            json=_UPGRADE["remembered_correction_body"],
            headers={**_auth(correction_replay_token), "Idempotency-Key": _UPGRADE["remembered_correction_key"]})
        assert correction_replay.status_code == 200, \
            f"replay of the remembered correction must stay a 200 replay: " \
            f"{correction_replay.status_code} {correction_replay.text}"
        correction_retry_identity = (correction_replay.status_code, correction_replay.json())

    statement_snapshot_page = None
    if _UPGRADE.get("statement_snapshot_token"):
        snap_token = tokens[_UPGRADE["statement_snapshot_handle"]]
        snap = _get(base_url, "/statement", headers=_auth(snap_token),
                    params={"limit": 5, "snapshot_token": _UPGRADE["statement_snapshot_token"]})
        assert snap.status_code == 200, f"remembered statement snapshot_token stopped resolving: " \
                                         f"{snap.status_code} {snap.text}"
        statement_snapshot_page = snap.json()

    return {
        "balances": balances,
        "identities": identities,
        "wallets": wallets,
        "requests": requests_state,
        "authorizations": auth_state,
        "settlement_id": _UPGRADE["settlement_id"],
        "settlement_members": settlement_members,
        "retry_identity": (replay.status_code, replay.json()),
        "capture_retry_identity": capture_retry_identity,
        "revision_state": revision_state,
        "correction_retry_identity": correction_retry_identity,
        "statement_snapshot_page": statement_snapshot_page,
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
