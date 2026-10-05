"""POST /payments/{id}/refunds — R-4-001, R-4-010..024.

R-4-022 (planner decision) gives this endpoint its own precedence chain,
the same shape corrections.py already established: lookup (404) and the
receiver check (403) come BEFORE the idempotency machinery, since "who
may even attempt this" has to be known before a key can be claimed
against it. That can't be expressed with `Endpoint`'s fixed hook order,
so this endpoint overrides `handle()` outright.

    401 -> 404 (unknown payment) -> 403 (non-receiver) -> 400 missing key
    -> idempotency resolution -> 422 validation_failed (amount)
    -> 422 invalid_refund_target -> 422 refund_exceeds_payment
    -> 409 insufficient_funds
"""
from __future__ import annotations

import secrets

from .. import auth
from ..errors import forbidden, insufficient_funds, invalid_refund_target, not_found, \
    refund_exceeds_payment, validation_failed
from ..holds import available_for
from ..idempotency import IDEMPOTENCY
from ..json_utils import now_rfc3339, parse_json_object
from ..pipeline import Endpoint, RequestCtx
from ..revisions import latest_revision, make_revision_1
from ..store import STORE
from ..validation import parse_amount, validate_idempotency_key
from .payments import serialize_payment

_MIN_AMOUNT = 1
_MAX_AMOUNT = 1_000_000_000


class RefundEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def handle(self, ctx: RequestCtx) -> tuple[int, dict]:
        ctx.user = auth.authenticate(STORE, ctx.headers.get("authorization"))

        target = STORE.payments.get(ctx.path_params.get("id"))
        if target is None:
            raise not_found("no such payment")
        # R-4-011: only the original receiver may refund; a non-party
        # (including the original sender) is 403, not a visibility-shaped
        # 404 -- the caller already knows this payment exists.
        if target["to_user_id"] != ctx.user["id"]:
            raise forbidden("only the original receiver may refund this payment")

        ctx.body = parse_json_object(ctx.raw_body)
        idem_key = validate_idempotency_key(ctx.headers.get("idempotency-key"))
        outcome, payload = IDEMPOTENCY.resolve_or_claim(ctx.user["id"], ctx.method, ctx.path, idem_key, ctx.body)
        if outcome == "replay":
            return payload
        composite = payload

        try:
            fields = self.validate_fields(ctx)

            # R-4-013: a refund of a refund is invalid, before any check
            # of the target's remaining balance or the caller's funds --
            # it is a property of the target, not of the wallet.
            if target.get("refund_of") is not None:
                raise invalid_refund_target()

            with STORE.write_lock():
                status, body = self._apply(target, fields)
        except Exception:
            # R-4-022: a rejected refund claims no key, the same rule
            # every other write path follows.
            IDEMPOTENCY.release(composite)
            raise

        IDEMPOTENCY.commit(composite, status, body)
        return status, body

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        if "amount" not in body:
            raise validation_failed("amount is required")
        amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)
        return {"amount": amount}

    def _apply(self, target: dict, fields: dict) -> tuple[int, dict]:
        target_id = target["id"]
        amount = fields["amount"]

        # R-4-015: the ceiling is the payment's CURRENT corrected amount
        # (its latest revision), not the original -- a correction can
        # raise or lower how much is ever refundable. Cumulative, not
        # per-call: this payment's own "refunded_total" is the stored
        # quantity N4-2's correction floor also reads, so both doors see
        # the same number.
        current = latest_revision(STORE.payment_revisions.get(target_id, []))
        current_amount = current["amount"] if current is not None else target["amount"]
        already_refunded = target.get("refunded_total", 0)
        if already_refunded + amount > current_amount:
            raise refund_exceeds_payment()

        # R-4-018: debited from the receiver's AVAILABLE funds (total
        # minus held), the same discipline every other debit uses.
        refund_payer_id = target["to_user_id"]
        refund_payee_id = target["from_user_id"]
        if available_for(STORE, refund_payer_id) < amount:
            raise insufficient_funds()

        target["refunded_total"] = already_refunded + amount

        STORE.wallets[refund_payer_id] = STORE.wallets.get(refund_payer_id, 0) - amount
        STORE.wallets[refund_payee_id] = STORE.wallets.get(refund_payee_id, 0) + amount

        refund_id = secrets.token_urlsafe(16)
        created_at = now_rfc3339()
        refund_payment = {
            "id": refund_id, "from_user_id": refund_payer_id, "to_user_id": refund_payee_id,
            # R-4-016: the ORIGINAL target's note/visibility, never the
            # refund call's own (which carries neither field at all).
            "amount": amount, "note": target["note"], "visibility": target["visibility"],
            "request_id": None, "settlement_id": None, "authorization_id": None,
            "refund_of": target_id,
            "created_at": created_at, "seq": STORE.next_seq(),
        }
        STORE.payments[refund_id] = refund_payment
        # R-4-023: a refund is an ordinary payment to the bitemporal
        # machinery -- its own revision 1, R-3-015's shape.
        STORE.payment_revisions[refund_id] = [make_revision_1(amount, created_at)]

        return 201, serialize_payment(refund_payment)


def register(router) -> None:
    router.add("POST", "/payments/{id}/refunds", RefundEndpoint())
