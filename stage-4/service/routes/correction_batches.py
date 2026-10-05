"""POST /correction-batches — R-4-040..048, R-4-060, R-4-061 (validation
half; commit semantics -- strict shared recorded_at ordering, replay,
correction_batch_id on the revision -- are N4-4).

R-4-049's precedence, implemented as four stages run in that order:

    1. item errors, STRICTLY in input order, each item fully resolved
       before the next is even looked at: field validation/duplicate
       payment_id (422 validation_failed) -> lookup (404 not_found) ->
       linked_payment_immutable (422) -> stale_revision (409) ->
       refund_exceeds_payment (422, R-4-033/035's floor).
    2. settlement-member effective-instant agreement (422
       validation_failed, R-4-046) and completeness over the UNION of
       settlements touched (422 incomplete_settlement, R-4-045/060) --
       both need every item's target already resolved, so they run after
       stage 1 completes for the whole batch, not per item.
    3. the BATCH's combined current-available funds check (409
       insufficient_funds, R-4-050) -- net delta per user across every
       item, not each item in isolation, mirroring settlements.py's own
       net-position check.
    4. historical boundaries (409 historical_overdraft) -- ALL of the
       batch's candidates applied TOGETHER, via
       would_candidates_cause_historical_overdraft(), not each item
       checked against everyone else's unchanged current revision.
       Two items can each land exactly on a boundary against the
       SIBLING's unchanged value while applying both at once drives
       that instant negative; a per-item check misses exactly that
       combination (confirmed exploitable, N4-3.1 BREACH).

Like corrections.py and refunds.py, this overrides handle() because the
dynamic checks in stages 1(partial)/3/4 read mutable store state
(revisions, refunded_total, wallets) that a concurrent write can change,
so they must run under the write lock, atomically, with the whole
batch's mutation -- stage 1's field/shape/lookup/immutability checks are
static (payments are never deleted and settlement_id/authorization_id/
refund_of never change after creation) and are safe to resolve first.
"""
from __future__ import annotations

import secrets
import time

from .. import auth
from ..errors import (forbidden, historical_overdraft, incomplete_settlement, insufficient_funds,
                       linked_payment_immutable, not_found, refund_exceeds_payment, stale_revision,
                       validation_failed)
from ..holds import available_for
from ..idempotency import IDEMPOTENCY
from ..json_utils import epoch_to_rfc3339, parse_json_object, parse_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import latest_revision, would_candidates_cause_historical_overdraft
from ..store import STORE
from ..validation import parse_amount, validate_idempotency_key

_MIN_AMOUNT = 0
_MAX_AMOUNT = 1_000_000_000
_MAX_REASON_LEN = 200
_MIN_ITEMS = 1
_MAX_ITEMS = 32


class CorrectionBatchEndpoint(Endpoint):
    has_body = True
    requires_idempotency_key = True

    def handle(self, ctx: RequestCtx) -> tuple[int, dict]:
        ctx.user = auth.authenticate(STORE, ctx.headers.get("authorization"))
        # R-4-040: the same operator rule as POST /settlements -- this
        # does not depend on the body, so it is checked before anything
        # about it, including idempotency.
        if ctx.user["id"] not in STORE.settlement_operator_ids:
            raise forbidden("settlement operator required")

        ctx.body = parse_json_object(ctx.raw_body)
        idem_key = validate_idempotency_key(ctx.headers.get("idempotency-key"))
        outcome, payload = IDEMPOTENCY.resolve_or_claim(ctx.user["id"], ctx.method, ctx.path, idem_key, ctx.body)
        if outcome == "replay":
            return payload
        composite = payload

        try:
            items = self._resolve_items(ctx.body)
            with STORE.write_lock():
                status, body = self._apply(items)
        except Exception:
            # R-4-051: a rejected batch claims no key.
            IDEMPOTENCY.release(composite)
            raise

        IDEMPOTENCY.commit(composite, status, body)
        return status, body

    def _resolve_items(self, body: dict) -> list[dict]:
        corrections = body.get("corrections")
        # R-4-041: the batch shape itself is a special field -- 422 even
        # for the wrong JSON type.
        if not isinstance(corrections, list) or not (_MIN_ITEMS <= len(corrections) <= _MAX_ITEMS):
            raise validation_failed("corrections must be an array of 1 to 32 entries")

        resolved: list[dict] = []
        seen_payment_ids: set[str] = set()
        for raw in corrections:
            # Stage 1, strictly in input order, each item fully resolved
            # (including its lookup and immutability, which are static)
            # before the next item is even parsed.
            item = self._resolve_one_item(raw, seen_payment_ids)
            seen_payment_ids.add(item["payment_id"])
            resolved.append(item)

        # R-4-046: members of one settlement must share one effective
        # instant -- compared as parsed instants, never as strings, so
        # equivalent offset spellings of the same instant agree.
        by_settlement: dict[str, list[dict]] = {}
        for item in resolved:
            settlement_id = item["payment"].get("settlement_id")
            if settlement_id is not None:
                by_settlement.setdefault(settlement_id, []).append(item)
        for members in by_settlement.values():
            instants = {m["effective_epoch"] for m in members}
            if len(instants) > 1:
                raise validation_failed(
                    "every settlement member corrected in one batch must share one effective instant")

        # R-4-045/060: completeness over the UNION of settlements the
        # batch touches, checked only after every per-item error above.
        for settlement_id, members in by_settlement.items():
            settlement = STORE.settlements.get(settlement_id)
            all_member_ids = set(settlement["payment_ids"]) if settlement else set()
            included_ids = {m["payment_id"] for m in members}
            if included_ids != all_member_ids:
                raise incomplete_settlement()

        return resolved

    def _resolve_one_item(self, raw, seen_payment_ids: set[str]) -> dict:
        if not isinstance(raw, dict):
            raise validation_failed("each correction item must be an object")
        for key in ("payment_id", "expected_revision", "amount", "effective_at", "reason"):
            if key not in raw:
                raise validation_failed(f"{key} is required on every correction item")

        payment_id = raw["payment_id"]
        if not isinstance(payment_id, str):
            raise validation_failed("payment_id must be a string")
        # R-4-061: the distinctness check runs WITH the per-item sweep,
        # in input order -- an earlier item's own error still wins over
        # a later duplicate pair, since this item is only reached once
        # every earlier item has already passed its own checks.
        if payment_id in seen_payment_ids:
            raise validation_failed("corrections must have distinct payment_ids")

        expected_revision = raw["expected_revision"]
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise validation_failed("expected_revision must be a positive integer")

        amount = parse_amount(raw["amount"], min_value=_MIN_AMOUNT, max_value=_MAX_AMOUNT)

        effective_at_raw = raw["effective_at"]
        if not isinstance(effective_at_raw, str):
            raise validation_failed("effective_at must be an RFC 3339 timestamp")
        try:
            effective_epoch = parse_rfc3339(effective_at_raw)
        except (ValueError, TypeError):
            raise validation_failed("effective_at must be an RFC 3339 timestamp with an explicit offset")
        # R-4-055 (carries R-3-053): no tolerance window.
        if effective_epoch > time.time():
            raise validation_failed("effective_at cannot be later than now")

        reason = raw["reason"]
        if not isinstance(reason, str) or not (1 <= len(reason) <= _MAX_REASON_LEN):
            raise validation_failed("reason must be a string of 1 to 200 characters")

        # R-4-043: lookup is static (payments are never deleted) and
        # safe outside the write lock.
        payment = STORE.payments.get(payment_id)
        if payment is None:
            raise not_found("no such payment")

        # R-4-044: a capture or refund is immutable at any revision --
        # settlement_id/authorization_id/refund_of never change after
        # creation, so this is also safe to resolve here.
        if payment.get("authorization_id") is not None or payment.get("refund_of") is not None:
            raise linked_payment_immutable()

        return {
            "payment_id": payment_id, "payment": payment,
            "expected_revision": expected_revision, "amount": amount,
            "effective_at": effective_at_raw, "effective_epoch": effective_epoch, "reason": reason,
        }

    def _apply(self, items: list[dict]) -> tuple[int, dict]:
        # Stage 1's dynamic half: stale_revision and the refund floor
        # both read mutable state, so they are re-checked here, under
        # the lock, for every item before anything is mutated -- the
        # whole batch is atomic, never a partial application.
        plans = []
        for item in items:
            payment_id = item["payment_id"]
            revisions = STORE.payment_revisions.setdefault(payment_id, [])
            current = latest_revision(revisions)
            if current is None or current["revision"] != item["expected_revision"]:
                raise stale_revision()

            new_amount = item["amount"]
            if new_amount < item["payment"].get("refunded_total", 0):
                raise refund_exceeds_payment()

            old_amount = current["amount"]
            delta = new_amount - old_amount
            plans.append({**item, "revisions": revisions, "current": current,
                          "old_amount": old_amount, "new_amount": new_amount, "delta": delta})

        # Stage 3: combined current-available funds, net per user across
        # every item (R-4-050) -- never each item in isolation.
        net: dict[str, int] = {}
        for plan in plans:
            payer_id, payee_id = plan["payment"]["from_user_id"], plan["payment"]["to_user_id"]
            net[payer_id] = net.get(payer_id, 0) - plan["delta"]
            net[payee_id] = net.get(payee_id, 0) + plan["delta"]
        for user_id, user_delta in net.items():
            if user_delta < 0 and available_for(STORE, user_id) + user_delta < 0:
                raise insufficient_funds()

        # Stage 4: historical boundaries, checked with ALL of the
        # batch's candidates applied TOGETHER (R-4-050) -- two items can
        # each land exactly on a boundary when checked against the
        # SIBLING's unchanged current revision, while applying both at
        # once drives that same instant negative. A per-item check
        # against everyone else's current value misses exactly that
        # combination.
        candidates = {plan["payment_id"]: (plan["new_amount"], plan["effective_at"]) for plan in plans}
        affected_user_ids = set()
        for plan in plans:
            affected_user_ids.add(plan["payment"]["from_user_id"])
            affected_user_ids.add(plan["payment"]["to_user_id"])
        if would_candidates_cause_historical_overdraft(STORE.opening_balances, STORE.payments,
                                                         STORE.payment_revisions, candidates, affected_user_ids,
                                                         store=STORE):
            raise historical_overdraft()

        # R-4-053: one shared recorded_at, strictly LATER than every
        # touched payment's own previous recorded_at -- never derived
        # from the clock alone, since a batch landing in the same tick
        # as a just-recorded single correction would otherwise tie
        # (R-3-004 requires a strict increase per payment).
        now_epoch = time.time()
        prior_epochs = [parse_rfc3339(plan["current"]["recorded_at"]) for plan in plans]
        recorded_epoch = max([now_epoch] + prior_epochs) + 0.000001
        recorded_at = epoch_to_rfc3339(recorded_epoch)
        correction_batch_id = secrets.token_urlsafe(16)
        revisions_out = []
        for plan in plans:
            payer_id, payee_id = plan["payment"]["from_user_id"], plan["payment"]["to_user_id"]
            STORE.wallets[payer_id] = STORE.wallets.get(payer_id, 0) - plan["delta"]
            STORE.wallets[payee_id] = STORE.wallets.get(payee_id, 0) + plan["delta"]

            new_revision = {
                "revision": plan["current"]["revision"] + 1,
                "amount": plan["new_amount"],
                "effective_at": plan["effective_at"],
                "recorded_at": recorded_at,
                "reason": plan["reason"],
                "correction_batch_id": correction_batch_id,
            }
            plan["revisions"].append(new_revision)
            revisions_out.append({
                "payment_id": plan["payment_id"],
                "revision": new_revision["revision"],
                "amount": new_revision["amount"],
                "effective_at": new_revision["effective_at"],
                "recorded_at": new_revision["recorded_at"],
                "reason": new_revision["reason"],
            })

        body = {
            "correction_batch_id": correction_batch_id,
            "recorded_at": recorded_at,
            "revisions": revisions_out,
        }
        return 201, body


def register(router) -> None:
    router.add("POST", "/correction-batches", CorrectionBatchEndpoint())
