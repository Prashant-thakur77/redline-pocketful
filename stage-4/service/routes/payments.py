"""POST /payments — R-1-006, R-1-130..140."""
from __future__ import annotations

import secrets

from ..errors import insufficient_funds, malformed_request, not_found, self_payment, validation_failed
from ..holds import available_for
from ..json_utils import now_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import make_revision_1
from ..store import STORE
from ..validation import HANDLE_RE, parse_amount, validate_note, validate_visibility

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000
_MAX_NOTE_LEN = 200


def serialize_payment(payment: dict) -> dict:
    from_user = STORE.users_by_id.get(payment["from_user_id"])
    to_user = STORE.users_by_id.get(payment["to_user_id"])
    return {
        "payment_id": payment["id"],
        "from_user_id": payment["from_user_id"],
        "from_handle": from_user["handle"] if from_user else None,
        "to_user_id": payment["to_user_id"],
        "to_handle": to_user["handle"] if to_user else None,
        "amount": payment["amount"],
        "currency": STORE.currency,
        "note": payment["note"],
        "visibility": payment["visibility"],
        "request_id": payment["request_id"],
        "created_at": payment["created_at"],
        "settlement_id": payment["settlement_id"],
        "authorization_id": payment.get("authorization_id"),
        # R-4-020: every payment that is not a refund exposes refund_of:
        # null -- .get() defaults it for every payment that predates
        # refunds (seeded, imported, or created before this stage),
        # never requiring each creation site to set it explicitly.
        "refund_of": payment.get("refund_of"),
    }


class PaymentsEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "to_handle" not in body or "amount" not in body:
            raise validation_failed("to_handle and amount are required")

        # R-1-076 order: presence -> wrong-type (non-special fields) ->
        # amount -> note -> visibility -> handle syntax -> self-reference.
        to_handle_raw = body["to_handle"]
        if not isinstance(to_handle_raw, str):
            raise malformed_request("to_handle must be a string")

        amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
        note = validate_note(body, max_length=_MAX_NOTE_LEN)
        visibility = validate_visibility(body)

        if not HANDLE_RE.match(to_handle_raw):
            raise validation_failed("to_handle must match ^[a-z0-9_]{1,20}$")
        if to_handle_raw == ctx.user["handle"]:
            raise self_payment()

        return {"to_handle": to_handle_raw, "amount": amount, "note": note, "visibility": visibility}

    def lookup(self, ctx: RequestCtx, fields: dict):
        to_user_id = STORE.users_by_handle.get(fields["to_handle"])
        if to_user_id is None:
            raise not_found("no such user")
        return STORE.users_by_id[to_user_id]

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        payer, payee = ctx.user, resource
        amount = fields["amount"]

        # R-2-002/R-2-013: a direct payment is checked against available
        # (total minus held), not total — held funds cannot fund a new
        # payment even though the wallet's raw total covers it.
        # R-1-002/R-1-006: compute both sides before applying either, so
        # there is never a window where the sender is debited and the
        # receiver not yet credited, or vice versa.
        if available_for(STORE, payer["id"]) < amount:
            raise insufficient_funds()
        payer_balance = STORE.wallets.get(payer["id"], 0)
        payee_balance = STORE.wallets.get(payee["id"], 0)

        STORE.wallets[payer["id"]] = payer_balance - amount
        STORE.wallets[payee["id"]] = payee_balance + amount

        payment_id = secrets.token_urlsafe(16)
        payment = {
            "id": payment_id, "from_user_id": payer["id"], "to_user_id": payee["id"],
            "amount": amount, "note": fields["note"], "visibility": fields["visibility"],
            "request_id": None, "settlement_id": None, "authorization_id": None,
            "created_at": now_rfc3339(), "seq": STORE.next_seq(),
        }
        STORE.payments[payment_id] = payment
        # R-3-003: revision 1 exists from the instant the payment does.
        STORE.payment_revisions[payment_id] = [make_revision_1(amount, payment["created_at"])]
        return 201, serialize_payment(payment)


def register(router) -> None:
    router.add("POST", "/payments", PaymentsEndpoint())
