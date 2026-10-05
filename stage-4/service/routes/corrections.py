"""POST /payments/{id}/corrections — R-3-050..069.

R-3-068 (planner decision) gives this endpoint its own precedence chain,
different from the generic one in `pipeline.py`: lookup (404) and the
payer check (403) come BEFORE the idempotency machinery, since "who may
even attempt this" has to be known before a key can be claimed against
it. That can't be expressed with `Endpoint`'s fixed hook order, so this
endpoint overrides `handle()` outright rather than bending the shared
pipeline to one endpoint's shape.

    401 -> 404 (unknown payment) -> 403 (non-sender) -> 400 missing key
    -> idempotency resolution -> 422 validation_failed (field rules)
    -> 422 linked_payment_immutable -> 409 stale_revision
    -> 409 insufficient_funds -> 409 historical_overdraft
"""
from __future__ import annotations

import time

from .. import auth
from ..errors import forbidden, historical_overdraft, insufficient_funds, linked_payment_immutable, \
    not_found, refund_exceeds_payment, stale_revision, validation_failed
from ..holds import available_for
from ..idempotency import IDEMPOTENCY
from ..json_utils import now_rfc3339, parse_json_object, parse_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import latest_revision, would_cause_historical_overdraft
from ..store import STORE
from ..validation import parse_amount, validate_idempotency_key

_MIN_AMOUNT = 0
_MAX_AMOUNT = 1_000_000_000
_MAX_REASON_LEN = 200


class CorrectionEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def handle(self, ctx: RequestCtx) -> tuple[int, dict]:
        ctx.user = auth.authenticate(STORE, ctx.headers.get("authorization"))

        payment = STORE.payments.get(ctx.path_params.get("id"))
        if payment is None:
            raise not_found("no such payment")
        # R-3-051: only the original sender may correct; a non-party and
        # the receiver are both 403, not a visibility-shaped 404 — the
        # caller already knows this payment exists (it's in the URL).
        if payment["from_user_id"] != ctx.user["id"]:
            raise forbidden("only the original sender may correct this payment")

        ctx.body = parse_json_object(ctx.raw_body)
        idem_key = validate_idempotency_key(ctx.headers.get("idempotency-key"))
        outcome, payload = IDEMPOTENCY.resolve_or_claim(ctx.user["id"], ctx.method, ctx.path, idem_key, ctx.body)
        if outcome == "replay":
            return payload
        composite = payload

        try:
            fields = self.validate_fields(ctx)

            # R-3-065/066, R-4-032: a settlement-member, capture-produced
            # or refund payment can never be corrected, at any revision.
            if (payment.get("settlement_id") is not None or payment.get("authorization_id") is not None
                    or payment.get("refund_of") is not None):
                raise linked_payment_immutable()

            with STORE.write_lock():
                status, body = self._apply(payment, fields)
        except Exception:
            # R-3-061: a rejected correction claims no key.
            IDEMPOTENCY.release(composite)
            raise

        IDEMPOTENCY.commit(composite, status, body)
        return status, body

    def validate_fields(self, ctx: RequestCtx) -> dict:
        body = ctx.body
        for key in ("expected_revision", "amount", "effective_at", "reason"):
            if key not in body:
                raise validation_failed(f"{key} is required")

        expected_revision = body["expected_revision"]
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise validation_failed("expected_revision must be a positive integer")

        amount = parse_amount(body["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)

        effective_at_raw = body["effective_at"]
        if not isinstance(effective_at_raw, str):
            raise validation_failed("effective_at must be an RFC 3339 timestamp")
        try:
            effective_epoch = parse_rfc3339(effective_at_raw)
        except (ValueError, TypeError):
            raise validation_failed("effective_at must be an RFC 3339 timestamp with an explicit offset")
        # R-3-053: "not later than now" stands verbatim, no tolerance
        # window (planner ruling, N3-5.1) — reads may ask about the
        # future (R-3-074's as_of/known_at), writes may not claim to have
        # happened in it.
        if effective_epoch > time.time():
            raise validation_failed("effective_at cannot be later than now")

        reason = body["reason"]
        if not isinstance(reason, str) or not (1 <= len(reason) <= _MAX_REASON_LEN):
            raise validation_failed("reason must be a string of 1 to 200 characters")

        return {
            "expected_revision": expected_revision, "amount": amount,
            "effective_at": effective_at_raw, "reason": reason,
        }

    def _apply(self, payment: dict, fields: dict) -> tuple[int, dict]:
        payment_id = payment["id"]
        revisions = STORE.payment_revisions.setdefault(payment_id, [])
        current = latest_revision(revisions)
        if current is None or current["revision"] != fields["expected_revision"]:
            raise stale_revision()

        old_amount = current["amount"]
        new_amount = fields["amount"]
        delta = new_amount - old_amount

        payer_id, payee_id = payment["from_user_id"], payment["to_user_id"]

        # R-4-033/035: the already-refunded total is a floor on the
        # corrected amount, and it outranks BOTH funds checks below --
        # read under the write lock, same as the revision check just
        # above, since a concurrent refund could move this number between
        # validation and here. R-4-015's ceiling and this floor read the
        # same stored quantity (payment["refunded_total"]) so the two
        # directions of R-4-002 can never drift apart.
        if new_amount < payment.get("refunded_total", 0):
            raise refund_exceeds_payment()

        # R-4-037 (planner decision, amending R-3-058/059/060): the
        # insufficient_funds check is on the INCREMENTAL debit against
        # the debited party's CURRENT available funds -- never an opening
        # balance, and never new_amount itself. An increase debits the
        # original sender; a decrease debits the original receiver,
        # since it takes back money they may have already spent. Both
        # directions are checked; only the historical-overdraft replay
        # below is about boundaries other than "right now".
        if delta > 0:
            if available_for(STORE, payer_id) < delta:
                raise insufficient_funds()
        elif delta < 0:
            if available_for(STORE, payee_id) < -delta:
                raise insufficient_funds()

        if would_cause_historical_overdraft(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                             payment_id, new_amount, fields["effective_at"],
                                             (payer_id, payee_id)):
            raise historical_overdraft()

        STORE.wallets[payer_id] = STORE.wallets.get(payer_id, 0) - delta
        STORE.wallets[payee_id] = STORE.wallets.get(payee_id, 0) + delta

        new_revision = {
            "revision": current["revision"] + 1,
            "amount": new_amount,
            "effective_at": fields["effective_at"],
            "recorded_at": now_rfc3339(),
            "reason": fields["reason"],
        }
        revisions.append(new_revision)

        body = {
            "payment_id": payment_id,
            "revision": new_revision["revision"],
            "amount": new_revision["amount"],
            "effective_at": new_revision["effective_at"],
            "recorded_at": new_revision["recorded_at"],
            "reason": new_revision["reason"],
        }
        return 201, body


def register(router) -> None:
    router.add("POST", "/payments/{id}/corrections", CorrectionEndpoint())
