"""GET /statement — R-3-030..044, R-3-079..092.

Statements ignore activity-feed visibility entirely (R-3-037): a payment
is in scope iff the caller sent or received it, full stop. They also
always use each payment's current (latest) revision (R-3-038/040/041),
never the as_of-style backdating selection `/me` uses — `balance_before`/
`latest_revision` in `revisions.py` are the shared primitives for that.

R-3-092 (planner ruling): `snapshot` is a FREEZE, never a cursor. One
opaque id names one frozen result (entry list + opening/closing balance),
stored in `STORE.statement_snapshots`; every response addressed through
it echoes that same id back unchanged (R-3-090). Paging within a frozen
result is done with the ordinary `offset`/`limit` query parameters
(R-3-082/086), exactly as on every other list endpoint — the token never
encodes a position. A token is issued unconditionally, even for a
zero-entry or single-page result (R-3-080): there is always a frozen
result to name. An unknown, foreign or pre-reset token is 404 (R-3-084),
checked before `limit`/`offset` are even parsed (R-3-091) so a token's
existence is never revealed by a differing error code; `from`/`to`/
`known_at` together with a `snapshot` is 422 (R-3-083).
"""
from __future__ import annotations

import secrets

from ..errors import not_found, validation_failed
from ..json_utils import parse_rfc3339
from ..pipeline import Endpoint, RequestCtx
from ..revisions import balance_before, latest_revision, select_known_revision
from ..store import STORE
from ..validation import parse_limit, parse_offset

_FAR_FUTURE_EPOCH = 253402300799.0  # 9999-12-31T23:59:59+00:00


class StatementEndpoint(Endpoint):
    def validate_fields(self, ctx: RequestCtx) -> dict:
        snapshot_param = ctx.query.get("snapshot")
        from_raw = ctx.query.get("from")
        to_raw = ctx.query.get("to")
        known_at_raw = ctx.query.get("known_at")

        frozen = None
        if snapshot_param is not None:
            # R-3-083: a snapshot pins an already-frozen result; it cannot
            # be combined with a request to compute a different window.
            if from_raw is not None or to_raw is not None or known_at_raw is not None:
                raise validation_failed("snapshot cannot be combined with from, to or known_at")
            # R-3-084/091: an unknown/foreign/pre-reset token is 404, checked
            # before limit/offset so a token's existence is never leaked by
            # which error code comes back.
            candidate = STORE.statement_snapshots.get(snapshot_param)
            if candidate is None or candidate.get("user_id") != ctx.user["id"]:
                raise not_found("no such snapshot")
            # R-1-005: defensive, in addition to import-side validation --
            # a stored snapshot this read path cannot safely serve (missing
            # or wrong-typed entries/opening_balance/closing_balance, from
            # a future field this check wasn't updated for, or any other
            # unforeseen shape problem) must never crash a plain read; it
            # is unresolvable the same way an unknown token is (R-3-084).
            if (not isinstance(candidate.get("entries"), list)
                    or isinstance(candidate.get("opening_balance"), bool)
                    or not isinstance(candidate.get("opening_balance"), int)
                    or isinstance(candidate.get("closing_balance"), bool)
                    or not isinstance(candidate.get("closing_balance"), int)):
                raise not_found("no such snapshot")
            frozen = candidate

        limit = parse_limit(ctx.query.get("limit"))
        offset = parse_offset(ctx.query.get("offset"))

        from_epoch = None
        to_epoch = None
        known_at_epoch = None
        if frozen is None:
            if from_raw is not None:
                try:
                    from_epoch = parse_rfc3339(from_raw)
                except (ValueError, TypeError):
                    raise validation_failed("from must be an RFC 3339 timestamp with an explicit offset")
            if to_raw is not None:
                try:
                    to_epoch = parse_rfc3339(to_raw)
                except (ValueError, TypeError):
                    raise validation_failed("to must be an RFC 3339 timestamp with an explicit offset")
            if known_at_raw is not None:
                # R-3-075: same validation discipline as as_of (R-3-020).
                try:
                    known_at_epoch = parse_rfc3339(known_at_raw)
                except (ValueError, TypeError):
                    raise validation_failed("known_at must be an RFC 3339 timestamp with an explicit offset")

        return {
            "frozen": frozen, "snapshot_param": snapshot_param,
            "from_epoch": from_epoch, "to_epoch": to_epoch,
            "known_at_epoch": known_at_epoch, "known_at_raw": known_at_raw,
            "limit": limit, "offset": offset,
        }

    def _compute_window(self, ctx: RequestCtx, fields: dict) -> dict:
        user_id = ctx.user["id"]
        from_epoch = fields["from_epoch"]
        to_epoch = fields["to_epoch"] if fields["to_epoch"] is not None else _FAR_FUTURE_EPOCH
        known_at_epoch = fields["known_at_epoch"]

        if from_epoch is not None and from_epoch > to_epoch:
            # R-3-043: from later than to is an empty window by construction,
            # not an error — both balances describe the same instant (`to`)
            # so the R-3-035 invariant still closes over zero entries.
            if fields["to_epoch"] is not None:
                balance = balance_before(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                          user_id, to_epoch, known_at_epoch=known_at_epoch)
            elif known_at_epoch is not None:
                balance = balance_before(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                          user_id, _FAR_FUTURE_EPOCH, known_at_epoch=known_at_epoch)
            else:
                balance = STORE.wallets.get(user_id, 0)
            return {"entries": [], "opening_balance": balance, "closing_balance": balance}

        rows = []
        for p in STORE.payments.values():
            is_from = p["from_user_id"] == user_id
            is_to = p["to_user_id"] == user_id
            if not (is_from or is_to):
                continue
            revisions = STORE.payment_revisions.get(p["id"], [])
            # R-3-071/077: known_at narrows to the latest revision RECORDED
            # by then; none recorded yet excludes the payment entirely —
            # never a zero-delta entry.
            rev = (select_known_revision(revisions, known_at_epoch) if known_at_epoch is not None
                   else latest_revision(revisions))
            if rev is None:
                continue
            effective_epoch = parse_rfc3339(rev["effective_at"])
            if from_epoch is not None and effective_epoch < from_epoch:
                continue
            if effective_epoch >= to_epoch:
                continue
            rows.append((effective_epoch, p, rev))

        rows.sort(key=lambda row: (row[0], row[1]["id"]))

        if from_epoch is not None:
            opening_balance = balance_before(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                              user_id, from_epoch, known_at_epoch=known_at_epoch)
        else:
            # The wallet's opening balance predates every payment by
            # definition, so it doesn't depend on what's known yet.
            opening_balance = STORE.opening_balances.get(user_id, 0)

        if fields["to_epoch"] is not None:
            closing_balance = balance_before(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                              user_id, to_epoch, known_at_epoch=known_at_epoch)
        elif known_at_epoch is not None:
            closing_balance = balance_before(STORE.opening_balances, STORE.payments, STORE.payment_revisions,
                                              user_id, _FAR_FUTURE_EPOCH, known_at_epoch=known_at_epoch)
        else:
            closing_balance = STORE.wallets.get(user_id, 0)

        entries = []
        running = opening_balance
        for effective_epoch, p, rev in rows:
            is_from = p["from_user_id"] == user_id
            delta = -rev["amount"] if is_from else rev["amount"]
            running += delta
            entries.append({
                "payment_id": p["id"],
                "payment": p["id"],
                "amount": delta,
                "delta": delta,
                "balance_after": running,
                "revision": rev["revision"],
                "effective_at": rev["effective_at"],
                "recorded_at": rev["recorded_at"],
                "authorization_id": p.get("authorization_id"),
            })

        return {"entries": entries, "opening_balance": opening_balance, "closing_balance": closing_balance}

    def apply(self, ctx: RequestCtx, resource, fields: dict):
        if fields["frozen"] is not None:
            snapshot_id = fields["snapshot_param"]
            frozen = fields["frozen"]
        else:
            # R-3-080: a token is issued unconditionally, even for a
            # zero-entry or single-page result.
            snapshot_id = secrets.token_urlsafe(16)
            frozen = {"user_id": ctx.user["id"], "known_at_raw": fields["known_at_raw"],
                      **self._compute_window(ctx, fields)}
            STORE.statement_snapshots[snapshot_id] = frozen

        limit, offset = fields["limit"], fields["offset"]
        all_entries = frozen["entries"]
        page = all_entries[offset:offset + limit]
        has_more = offset + limit < len(all_entries)

        body = {
            "entries": page,
            "opening_balance": frozen["opening_balance"],
            "closing_balance": frozen["closing_balance"],
            "has_more": has_more,
            # R-3-090: a snapshot-paged response echoes the same token it
            # was given; it never changes between pages.
            "snapshot": snapshot_id,
        }
        # R-3-076: a supplied known_at is echoed back exactly as given,
        # including when replayed from a frozen snapshot on a later page.
        if frozen.get("known_at_raw") is not None:
            body["known_at"] = frozen["known_at_raw"]
        return 200, body


def register(router) -> None:
    router.add("GET", "/statement", StatementEndpoint())
