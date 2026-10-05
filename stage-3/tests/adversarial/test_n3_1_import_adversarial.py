"""Adversarial finding against N3-1's import path (R-3-018b), attacked at
commit e481fcd.

BREACH: `store.apply_import` computes `opening_balances` via
`compute_opening_balances(fields["wallets"], fields["payments"])` but,
unlike the reset path (`fixtures.validate_fixture`, fixed at `e481fcd` for
BREACH `0dfd763`), never calls `validate_payment_history_nonnegative` —
confirmed by `snapshot.validate_import_document`, which only runs
`check_nonnegative_balances(wallets)` (the current/ending balances) and
never touches the payment history's implied opening or intermediate
balances at all.

So a document whose payments list implies a negative opening balance for
some user sails through `POST /_test/import` with `204`, and that
negative figure is then directly retrievable via
`GET /me?as_of=<before the earliest payment>` (R-3-024) — the exact
R-3-002 violation ("no balance is negative in any historical view ...
not at any past effective-time") that the reset-path fix for BREACH
`0dfd763` closed on the reset side only.
"""
from __future__ import annotations

import copy
import uuid
from datetime import datetime, timedelta, timezone

from conftest import api_get, api_post, auth, login_token, reset_ok, two_user_fixture


def test_import_rejects_a_document_whose_payment_implies_a_negative_opening_balance():
    """R-3-018b: the import path must reject a document whose payment
    history implies a negative balance at any point, exactly like reset
    does (R-3-018/R-3-002) -- not just check the current ending wallets."""
    fixture, token_a, token_b = two_user_fixture(balance_a=1000, balance_b=1000)
    document = api_get("/_test/export").json()

    e_uid = document["state"]["users"][0]["id"]
    f_uid = document["state"]["users"][1]["id"]
    f_email = document["state"]["users"][1]["email"]

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    doc2 = copy.deepcopy(document)
    doc2["state"]["payments"].append({
        "id": f"pay{uuid.uuid4().hex[:8]}", "from_user_id": e_uid, "to_user_id": f_uid, "amount": 50000,
        "note": "", "visibility": "public", "request_id": None, "settlement_id": None,
        "authorization_id": None, "created_at": past, "seq": 1,
    })
    # wallets are left unchanged (both still 1000), so f's derived opening
    # balance is 1000 - 50000 = -49000: deeply, unambiguously negative.

    r = api_post("/_test/import", json=doc2)
    assert r.status_code == 422, (
        f"R-3-018b: import must reject a document whose payment history implies a negative "
        f"opening balance, exactly as reset does -- got {r.status_code}: {r.text}"
    )

    # Belt and suspenders: if the import were (wrongly) accepted, show the
    # negative balance surfacing live through GET /me?as_of, which is the
    # concrete R-3-002 violation this check exists to prevent.
    if r.status_code in (200, 201, 204):
        token_f = login_token(f_email)
        ancient = "1970-01-01T00:00:00+00:00"
        me = api_get("/me", headers=auth(token_f), params={"as_of": ancient}).json()
        assert me["balance"] >= 0, (
            f"R-3-002: GET /me?as_of=<before the earliest payment> must never show a negative "
            f"historical balance, got {me['balance']}"
        )
