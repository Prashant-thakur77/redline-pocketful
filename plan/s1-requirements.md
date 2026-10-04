# Stage 1 requirements — pocketful: payments and settlements

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-1.md`.
Every `§` reference below is to that file. `R-1-nnn` ids are permanent; later stages
carry them forward unchanged.

Kinds: **invariant**, **behaviour**, **error**, **limit**, **deploy**.

## A. Invariants — these hold at every read, under concurrency and retries

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-001 | The sum of all wallet balances always equals the sum of the `balance` values seeded by the last successful `POST /_test/reset` (or restored by `POST /_test/import`), at every read, after any mix of concurrent payments, request payments, splits, settlements and replays. | §1.1, §9 | invariant |
| R-1-002 | No wallet balance is ever negative, not even transiently: no observable read and no intermediate state inside any operation leaves a balance below zero. | §1.2 | invariant |
| R-1-003 | A payment request moves money at most once: a replayed write returns the original response and makes no further state change. | §1.3, §7 | invariant |
| R-1-004 | Every amount in the API and in storage is an exact integer count of minor units; no floating-point rounding error is ever observable, and split shares sum exactly to the split `amount`. | §4, §9 | invariant |
| R-1-005 | No request produces a 5xx response, including under 50 concurrent in-flight requests. | §5 | invariant |
| R-1-006 | Concurrent requests produce results equal to executing them one at a time in some order (serializable); the debit and credit of a payment are one atomic step, never visible in one wallet and not the other, and a failed payment leaves no trace in either wallet. | §8 `POST /payments` | invariant |
| R-1-007 | A rejected write (any 4xx) changes no balance, creates no payment, no request and no settlement, and leaves no record other than those the idempotency rules require. | §5, §7, §11 | invariant |

## B. Delivery and deployment

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-010 | The stage folder contains a `Dockerfile` that builds the service with no manual setup, and a `RUN.md` giving the exact build-and-start command. | §2 | deploy |
| R-1-011 | The image runs standalone with `-e PORT=<port>` and a port mapping; no compose file, external service, volume or sidecar is needed to start or serve. | §2 | deploy |
| R-1-012 | The service listens on `0.0.0.0` on the port given by the `PORT` environment variable, defaulting to `8080` when `PORT` is unset. | §3.1 | deploy |
| R-1-013 | The container makes no outbound network request at run time; all dependencies, fonts, scripts, stylesheets and seed data are baked into the image during build. | §2 | deploy |
| R-1-014 | `GET /health` returns `200` with body `{"status": "ok"}` once the service and its data store can serve requests, within 60 s of container start. Non-200 before readiness is permitted. | §3.2 | behaviour |
| R-1-015 | The service stays correct and responsive within 2 vCPU and 2 GiB with up to 50 requests in flight; every request other than the test-control endpoints completes within 5 s, and `POST /_test/reset`, `POST /_test/import` and `GET /_test/export` within 10 s. | §2 limits, §10 | limit |
| R-1-016 | Service state need not survive a container restart; no on-disk durability is required. | §2 | deploy |

## C. Conventions

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-020 | Every JSON response carries `Content-Type: application/json; charset=utf-8`, and request bodies are read as UTF-8 JSON. | §3.4 | behaviour |
| R-1-021 | Every timestamp in a response is RFC 3339 with an explicit offset (e.g. `2026-09-24T19:00:00+00:00`); a bare local time or a `Z`-less naive form is never emitted. | §3.4 | behaviour |
| R-1-022 | Unknown fields in any request body are ignored and are never an error. | §3.4 | behaviour |
| R-1-023 | Unknown query parameters on any endpoint are ignored and are never an error. | §3.4 | behaviour |
| R-1-024 | Every id the service assigns is an opaque string of at most 64 characters; format is the implementation's choice but ids are unique within their kind for the life of a reset. | §3.4 | behaviour |
| R-1-025 | Seeded ids supplied in a fixture are used verbatim as the service's ids for those users, payments and requests, and are returned unchanged by the API. | §4 fixture | behaviour |

## D. Model: currency, users, handles

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-030 | The service has exactly one currency and one `minor_units` value, both declared by the fixture; `minor_units` is `0`, `2` or `3`, and fixtures use `EUR` (2), `JPY` (0) and `BHD` (3). | §4 | behaviour |
| R-1-031 | Every API `amount` is an integer count of minor units; JSON `1000`, `1000.0` and `1e3` are all accepted as the same valid amount because their numeric value is integral. | §4 | behaviour |
| R-1-032 | A JSON boolean or string in an `amount` field is not a number and is rejected with `422 validation_failed` (not `400`). | §4, §5 | error |
| R-1-033 | A numeric `amount` with a non-integral value (e.g. `10.5`, `1e-1`) is `422 validation_failed`. | §8 | error |
| R-1-034 | Every user has a handle that is unique across the service, matches `^[a-z0-9_]{1,20}$`, and never changes once set. | §4 | behaviour |
| R-1-035 | Recipients and payers are identified in request bodies by handle only; no directory or user-search endpoint exists. | §4 | behaviour |
| R-1-036 | A user created through `POST /auth/signup` gets a handle derived from the email: take the local part (everything before the first `@`), lowercase it, replace every character outside `[a-z0-9_]` with `_`, then truncate to 20 characters. | §4, §6 | behaviour |
| R-1-037 | A newly signed-up user starts with balance `0`, can immediately receive money and can immediately be asked for money. | §4 | behaviour |

## E. Fixture, reset, and seeding

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-040 | `POST /_test/reset` with a fixture body replaces **all** service state and returns `204 No Content`; after it returns, every subsequent request sees only that fixture and nothing from before it. | §3.3 | behaviour |
| R-1-041 | `POST /_test/reset` requires no authentication, is enabled in the delivered image, and may be called repeatedly; each call fully replaces the previous state. | §3.3 | behaviour |
| R-1-042 | A reset fixture seeds `currency`, `minor_units`, `users` (`id`, `email`, `password`, `display_name`, `handle`, `balance`), optional `payments` (`id`, `from_user_id`, `to_user_id`, `amount`, `note`, `visibility`), optional `requests` (`id`, `requester_id`, `payer_id`, `amount`, `note`, `status`) and optional `settlement_operator_ids` (default `[]`). | §4, §11 | behaviour |
| R-1-043 | A seeded user's `balance` is the wallet balance **after** every seeded payment; seeded payments are **not** replayed against balances, so loading them leaves the seeded balance unchanged. | §4 | behaviour |
| R-1-044 | Seeded users can log in with the seeded plaintext `password` immediately after reset. | §4 | behaviour |
| R-1-045 | A fixture containing any `balance` below zero makes `POST /_test/reset` return `422 validation_failed` and change nothing (the prior state remains fully intact and servable). | §4 | error |
| R-1-046 | A reset body that does not parse as JSON, or whose top level is not a JSON object, is `400 malformed_request` and changes nothing. | §5 | error |
| R-1-047 | A fixture that is structurally unusable — a missing required user field, a duplicate user `id` or `handle`, a `handle` not matching `^[a-z0-9_]{1,20}$`, a `minor_units` outside `{0,2,3}`, a payment or request referencing an unknown user id, or a seeded `status` outside the four request statuses — is `422 validation_failed` and changes nothing. | §4, §5 | error |
| R-1-048 | Any field the fixture does not mention is ignored, and a fixture omitting `payments`, `requests` or `settlement_operator_ids` is valid; the omitted collection is empty. | §3.4, §4, §11 | behaviour |
| R-1-049 | Seeded requests keep their seeded `status`; a seeded non-`pending` request is not payable and a seeded `pending` request is payable exactly like an API-created one. | §4, §8 | behaviour |
| R-1-050 | There is no administrative balance endpoint, and no endpoint other than reset/import may set a balance directly. | §4 | behaviour |
| R-1-051 | **Decision (planner, 2026-10-04).** The fixture's request fields (§4) give no way to name the payment that settled a seeded request, so a seeded `paid` request exposes **`payment_id: null`**. The service must **not** synthesize a payment for it. A synthesized payment would appear in `GET /activity` for its two parties although no fixture declared it (R-1-191), and — decisively — it would be a payment record that moved no money, so in stage 3 `GET /statement` would compute a delta for it and break `opening_balance + Σ delta == closing_balance` (R-3-010) for both parties permanently. `payment_id` is non-null only for a request actually paid through `POST /requests/{id}/pay`. | §4, §8, s3 §statement | behaviour |

## F. Errors and precedence

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-060 | Every 4xx and 5xx response body is exactly `{"error": {"code": "<code>", "message": "<any wording>"}}` with the specified status and code; `message` wording is free but must be a non-empty string. | §5 | error |
| R-1-061 | `400 malformed_request`: the body does not parse as JSON, the top level is not a JSON object, or a field is of the wrong JSON type and no endpoint-specific rule overrides it. | §5 | error |
| R-1-062 | `400 missing_idempotency_key`: a required `Idempotency-Key` header is absent or empty. | §5, §7 | error |
| R-1-063 | `401 unauthenticated`: the `Authorization` header is missing, not of the form `Bearer <token>`, or carries an unknown token. | §5, §6 | error |
| R-1-064 | `403 forbidden`: the caller is authenticated but not permitted to act on this resource. | §5 | error |
| R-1-065 | `404 not_found`: no such resource, or the resource is not visible to this caller. | §5 | error |
| R-1-066 | `409 idempotency_key_reuse`: the key was already used by this caller with a different request body on the same method and path. | §5, §7 | error |
| R-1-067 | `422 validation_failed`: a required field or query parameter is missing, or a stated rule is violated and no more specific code applies. | §5 | error |
| R-1-068 | A field of the **correct** JSON type with an invalid format or out-of-range value is `422 validation_failed` unless the endpoint names a different code; this covers invalid instants, negative counts and values over a stated maximum or length. | §5 | error |
| R-1-069 | Endpoint field rules take precedence over the wrong-type rule for these three fields: an invalid `amount` (including a string or boolean), a non-string `note` (including `null`), and any `visibility` other than `"public"` or `"private"` are all `422 validation_failed`, never `400`. | §5 | error |
| R-1-070 | Omitting an optional field selects its default and is never an error; omitting a required field is `422 validation_failed`. | §5 | error |
| R-1-071 | An integer-valued **query parameter** must be written as plain decimal digits; `1e9`, `4.0`, `+4`, ` 4`, `0x4` and an empty value are `422 validation_failed` whatever their numeric value. A leading `-` is only valid where negative values are. | §5 | error |
| R-1-072 | `Idempotency-Key` must be 1 to 255 characters: longer than 255 is `422 validation_failed`; absent or empty is `400 missing_idempotency_key`. | §5, §7 | error |
| R-1-073 | `limit` is an integer 1 to 200; anything else (including `0`, `201`, negative or non-digit forms) is `422 validation_failed`. | §5, §8 | error |
| R-1-074 | `offset` is an integer 0 or more; anything else is `422 validation_failed`. | §5, §8 | error |
| R-1-075 | **Decision (ambiguity resolved by the planner).** Error precedence on every endpoint is, in order: (1) `401 unauthenticated`; (2) endpoint-level permission that does not depend on the body (`403 forbidden` for a non-operator on `POST /settlements`); (3) `400 malformed_request` for an unparseable or non-object body; (4) `400 missing_idempotency_key`; (5) `422 validation_failed` for an over-long `Idempotency-Key`; (6) idempotency resolution (`200` replay or `409 idempotency_key_reuse`); (7) endpoint field validation (`422`, including `self_payment` / `self_request`); (8) resource lookup (`404 not_found`); (9) permission on the looked-up resource (`403 forbidden`); (10) resource-state checks (`409 request_not_pending`); (11) funds (`409 insufficient_funds`). | §5, §7, §8, §11 | error |
| R-1-076 | **Decision.** Within step (7) of R-1-075, body fields are validated in this fixed order so the returned code is deterministic: required-field presence → wrong-type fields → `amount` range and integrality → `note` length → `visibility` value → handle syntax → duplicate/empty collection rules → self-reference (`self_payment` / `self_request`). | §5 | error |
| R-1-077 | **Decision.** A `to_handle`, `payer_handle` or participant handle that is a string but does not match `^[a-z0-9_]{1,20}$` is `422 validation_failed` (R-1-068); a syntactically valid handle with no such user is `404 not_found`. A non-string handle is `400 malformed_request`. | §4, §5 | error |
| R-1-078 | A 4xx response never leaks a resource the caller may not see: a request or payment the caller is not party to is reported with the same code and body as a nonexistent one, except where the spec names `403 forbidden`. | §5 | error |
| R-1-079 | **Decision (from @adversary's N1-1 breach).** Every HTTP request reaching the service gets an HTTP response carrying the R-1-060 envelope, whatever its method, headers or framing — no 5xx and no dropped connection. `HEAD` on a `GET`-able path answers exactly as `GET` with no body; `OPTIONS` answers `204` with an `Allow` header; any other method, or a method not allowed on a routed path, is `405 method_not_allowed`; an unparseable, negative or over-cap `Content-Length`, an over-long request line or header block, and any other framing error are `400 malformed_request`. No server-framework default error page (HTML `501`, `400`, `414`, `431`) may ever be emitted. | §5, §1.5 | error |

## G. Authentication

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-080 | `POST /auth/signup` with `{"email","password","display_name"}` returns `201 {"user_id","display_name","token"}` and creates a usable account with a derived handle (R-1-036) and balance `0`. | §6 | behaviour |
| R-1-081 | There is no `handle` field in the signup body; a supplied one is ignored (R-1-022). | §4, §6 | behaviour |
| R-1-082 | `POST /auth/login` with `{"email","password"}` returns `200 {"user_id","display_name","token"}` for a correct password. | §6 | behaviour |
| R-1-083 | Signup with an already-registered email is `409 email_taken` and creates nothing. | §6 | error |
| R-1-084 | A signup `password` shorter than 8 characters is `422 validation_failed`. | §6 | error |
| R-1-085 | A signup `email` not of the form `local@domain` (empty local part, no `@`, empty domain) is `422 validation_failed`. | §6 | error |
| R-1-086 | Login with a wrong password or an unknown email is `401 unauthenticated`, with no distinction between the two cases. | §6 | error |
| R-1-087 | Signup whose derived handle is already taken by another account is `409 handle_taken` and creates no account. | §4, §6 | error |
| R-1-088 | **Decision.** Signup precedence is: `422 validation_failed` (field rules) → `409 email_taken` → `409 handle_taken`. A repeat signup with the same email therefore returns `email_taken`, never `handle_taken`. | §6 | error |
| R-1-089 | Every endpoint except `/health`, `/_test/*`, `POST /auth/signup` and `POST /auth/login` requires `Authorization: Bearer <token>`; without it the response is `401 unauthenticated`. | §6 | error |
| R-1-090 | Tokens never expire, and one account may hold many valid tokens used concurrently; a new login does not invalidate an earlier token. | §6 | behaviour |
| R-1-091 | Passwords are stored only as a bcrypt/scrypt/Argon2-class hash; no plaintext or reversibly encoded password is stored anywhere in service state. | §6 | behaviour |
| R-1-092 | Token comparison is exact; a token that is a prefix, suffix or case variant of a valid token is `401 unauthenticated`. | §6 | error |

## H. Idempotency

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-100 | Exactly five write paths require `Idempotency-Key`: `POST /payments`, `POST /requests`, `POST /requests/{id}/pay`, `POST /splits` and `POST /settlements`. No other endpoint requires or honours one. | §7, §11 | behaviour |
| R-1-101 | Idempotency state is scoped to the authenticated **user**: two different users may use the same key string on the same path with no interaction. | §7 | behaviour |
| R-1-102 | A replay is the same user sending the same method, the same path **and** the same body; the same key with the same body on a different path is a different request and succeeds normally. | §7 | behaviour |
| R-1-103 | First use of a key returns the endpoint's normal success status, `201`. | §7 | behaviour |
| R-1-104 | A replay returns `200` with a body identical to the original response **as a JSON value**. | §7 | behaviour |
| R-1-105 | The same key with a different body is `409 idempotency_key_reuse` and changes nothing. | §7 | error |
| R-1-106 | "Same body" means the same JSON value after parsing: key order and whitespace do not matter, but `{}` and `{"visibility":"public"}` are different values, as are `{"amount":1000}` and `{"amount":1000.0}`… **Decision:** bodies are compared as parsed JSON values with numbers compared by exact numeric value, so `1000`, `1000.0` and `1e3` in the same field **are** the same body; absent versus present-with-default-value keys are **different** bodies. | §7, §8 | behaviour |
| R-1-107 | A key reused after the original request failed with any 4xx is treated as a first use and may succeed. | §7 | behaviour |
| R-1-108 | For N concurrent identical requests with an unused key, exactly one returns `201` and the rest return `200` with the identical body; the operation takes effect exactly once. | §7 | invariant |
| R-1-109 | A successful replay returns the original response even after the underlying resource has changed, been paid, declined or cancelled, and makes no further state change. | §7 | behaviour |
| R-1-110 | Once the body has parsed as a JSON object and the caller is authenticated, a claimed key is resolved **before** endpoint field validation and before any current-resource check; so replaying a successful key with an invalid body still returns `409 idempotency_key_reuse`, and replaying a successful `pay` returns `200` rather than `409 request_not_pending`. | §7, §8 | behaviour |
| R-1-111 | A claimed key's stored record keeps the request body, the response status and the full response body, and survives export/import (R-1-206). | §7, §10 | behaviour |
| R-1-112 | **Decision.** A replay returns the stored response body **verbatim**; it is never re-rendered from the current resource. So a replay of a key claimed under an earlier stage's schema returns exactly that earlier body, without any field a later stage added to the resource (e.g. no `authorization_id`, no `refund_of`). This is what makes R-1-104 and R-1-206 hold across an upgrade. | §7, §10 | behaviour |

## I. `GET /me`

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-120 | `GET /me` returns `200 {"user_id","display_name","handle","balance","currency","minor_units"}` for the authenticated caller, with `balance` the caller's current wallet balance in minor units. | §8 | behaviour |

## J. `POST /payments`

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-130 | `POST /payments` with `{"to_handle","amount","note","visibility"}` moves `amount` from the caller to the handle's owner immediately and atomically, returning `201` with the payment object. | §8 | behaviour |
| R-1-131 | The payment object is `{"payment_id","from_user_id","from_handle","to_user_id","to_handle","amount","currency","note","visibility","request_id","created_at","settlement_id"}`; `request_id` is `null` for a direct payment and `settlement_id` is `null` for a payment outside a settlement. | §8, §11 | behaviour |
| R-1-132 | `note` is optional and defaults to `""`; `visibility` is optional and defaults to `"public"`. | §8 | behaviour |
| R-1-133 | A caller whose balance is below `amount` gets `409 insufficient_funds` and nothing changes. | §8 | error |
| R-1-134 | `amount` below `1`, above `1000000000`, or not integral is `422 validation_failed`. | §8 | error |
| R-1-135 | `to_handle` equal to the caller's own handle is `422 self_payment`. | §8 | error |
| R-1-136 | `note` longer than 200 characters (counted in Unicode code points) is `422 validation_failed`. | §8 | error |
| R-1-137 | `visibility` other than `"public"` or `"private"` is `422 validation_failed`. | §8 | error |
| R-1-138 | A syntactically valid `to_handle` with no owner is `404 not_found`. | §8 | error |
| R-1-139 | `note` is stored and returned verbatim — no trimming, escaping, case change or Unicode normalisation; Unicode and emoji survive a round trip byte for byte. | §8 | behaviour |
| R-1-140 | No operation produces a balance outside ±2⁵³, and monetary arithmetic preserves exact minor-unit values. | §4 | invariant |

## K. Requests

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-150 | `POST /requests` with `{"payer_handle","amount","note"}` creates a `pending` request with the caller as requester, returning `201` with `{"request_id","requester_id","requester_handle","payer_id","payer_handle","amount","currency","note","status","payment_id","created_at"}` and `payment_id: null`. | §8 | behaviour |
| R-1-151 | `POST /requests` never checks the payer's balance: a request for more than the payer holds is created normally and sits `pending`. | §4, §8 | behaviour |
| R-1-152 | A request carries no `visibility` of its own and never appears in any activity feed. | §4 | behaviour |
| R-1-153 | `POST /requests` errors: `amount` out of range or non-integral → `422 validation_failed`; `payer_handle` equal to the caller's handle → `422 self_request`; `note` over 200 characters → `422 validation_failed`; unknown handle → `404 not_found`. | §8 | error |
| R-1-154 | A request's lifecycle is `pending` then exactly one of `paid`, `declined`, `cancelled`; the terminal states are final. | §4 | behaviour |
| R-1-155 | `POST /requests/{id}/pay` with optional body field `visibility` (default `"public"`) is callable only by the payer; it returns `201` with the created payment in exactly the `POST /payments` shape, with `request_id` set to this request. | §8 | behaviour |
| R-1-156 | On a successful pay the request becomes `paid` and carries the new `payment_id`; the visibility is the payer's choice, not the requester's. | §4, §8 | behaviour |
| R-1-157 | `POST /requests/{id}/pay` body carries `visibility` only, so `{}` and `{"visibility":"public"}` are different JSON values and reusing one key across them is `409 idempotency_key_reuse`. | §8 | error |
| R-1-158 | Paying a request that is not `pending` is `409 request_not_pending`; a payer balance below `amount` is `409 insufficient_funds`; a caller who is not the request's payer (including a third party) is `403 forbidden`; an unknown request id is `404 not_found`. | §8 | error |
| R-1-159 | Replaying a successful pay returns `200` with the original payment body even though the request is now `paid`; it moves no additional money and never returns `409 request_not_pending`. | §8 | behaviour |
| R-1-160 | `POST /requests/{id}/decline` takes no idempotency key, is callable only by the payer, returns `200` with the request at `status: "declined"`; declining an already-`declined` request is `200` with the current state; a `paid` or `cancelled` request is `409 request_not_pending`; a non-payer is `403 forbidden`; unknown id is `404 not_found`. | §8 | behaviour |
| R-1-161 | `POST /requests/{id}/cancel` takes no idempotency key, is callable only by the requester, returns `200` with the request at `status: "cancelled"`; cancelling an already-`cancelled` request is `200`; a `paid` or `declined` request is `409 request_not_pending`; a non-requester is `403 forbidden`; unknown id is `404 not_found`. | §8 | behaviour |
| R-1-162 | Decline and cancel move no money and never change any balance. | §8 | invariant |
| R-1-163 | `GET /requests` returns only requests where the caller is the requester or the payer, newest first by `created_at`, as `{"requests":[…],"has_more":bool}`. | §8 | behaviour |
| R-1-164 | `GET /requests?direction=incoming` returns requests where the caller is the **payer**; `direction=outgoing` where the caller is the **requester**; absent returns both. | §8 | behaviour |
| R-1-165 | `GET /requests?status=<s>` filters to one of `pending`, `paid`, `declined`, `cancelled`; absent returns all. An unknown `direction` or `status` value is `422 validation_failed`. | §8 | error |
| R-1-166 | `GET /requests` `limit` defaults to 50 (range 1..200) and `offset` defaults to 0 (0 or more); `has_more` is `true` exactly when at least one matching item exists beyond the last one returned. | §8 | behaviour |
| R-1-167 | An `offset` beyond the end of the result set returns an empty list with `has_more: false`. | §8 | behaviour |

## L. Splits

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-170 | `POST /splits` with `{"amount","participant_handles","note"}` computes one share per participant in the given order and creates one `pending` request, with the caller as requester, for every participant **except** the caller, each for that participant's share. | §8 | behaviour |
| R-1-171 | The response is `201 {"split_id","amount","currency","note","shares":[{"handle","amount"}…],"requests":[…],"created_at"}`; `shares` covers every participant including the caller in the order given, and `requests` covers every participant except the caller in the same order. | §8 | behaviour |
| R-1-172 | `shares` always sums exactly to `amount`. | §8, §9 | invariant |
| R-1-173 | Shares are whole minor units, differ by at most one minor unit, and the larger shares go to the first participants in `participant_handles` order: with `base = amount // n` and `rem = amount % n`, share `i` is `base + 1` for `i < rem` and `base` otherwise. | §9 | behaviour |
| R-1-174 | The rule reproduces: 1000/3 → 334,333,333; 1/3 → 1,0,0; 10/3 → 4,3,3; 999/3 → 333,333,333; 5/5 → 1,1,1,1,1. | §9 | behaviour |
| R-1-175 | Reordering `participant_handles` gives the extra unit to a different participant; a share of `0` is legal and still produces a request for that participant. | §9 | behaviour |
| R-1-176 | A split whose only participant is the caller is valid: it computes one share, creates zero requests and returns `"requests": []`. | §8 | behaviour |
| R-1-177 | Nothing about a split checks any balance, and a split moves no money. | §8 | invariant |
| R-1-178 | `POST /splits` errors: `amount` out of range or non-integral → `422 validation_failed`; `participant_handles` empty or containing a duplicate handle → `422 validation_failed`; `note` over 200 characters → `422 validation_failed`; any unknown handle → `404 not_found`. | §8 | error |
| R-1-179 | **Decision.** `participant_handles` absent or not a JSON array is `422 validation_failed` (missing/invalid required field); an element that is not a string is `400 malformed_request`; a string element of invalid handle syntax is `422 validation_failed` (R-1-077). | §5, §8 | error |
| R-1-180 | Each split's shares are computed independently of every previous split; after any number of splits have been paid in full, balances still sum exactly to the seeded total. | §9 | invariant |

## M. `GET /activity` and the feed contract

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-190 | `GET /activity` returns payments only, newest first by `created_at`, as `{"payments":[…],"has_more":bool}`. | §8 | behaviour |
| R-1-191 | A payment appears for a caller **if and only if** its `visibility` is `public`, or the caller is its sender, or the caller is its receiver. There is no other rule, no follow graph and no mute list. | §4 | behaviour |
| R-1-192 | `visibility` is one value on the payment, seen identically by both parties and by third parties; a `private` payment is hidden from third parties but visible to its own sender and receiver. | §4 | behaviour |
| R-1-193 | Requests never appear in `GET /activity`, and a split is not a feed item. | §4 | behaviour |
| R-1-194 | `GET /activity` `limit` and `offset` behave exactly as on `GET /requests` (R-1-166, R-1-167, R-1-073, R-1-074). | §8 | behaviour |
| R-1-195 | The relative order of two payments created within the same second is unspecified, and stable pagination during concurrent writes is not required for `GET /activity`. | §8 | behaviour |
| R-1-196 | A settlement member payment follows the same feed visibility rule as any other payment. | §11 | behaviour |

## N. Export and import

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-200 | `GET /_test/export` is unauthenticated and returns `200` with a JSON object containing `track: "pocketful"`, `format_version: 1` and `state` (an implementation-defined JSON object). | §10 | behaviour |
| R-1-201 | `POST /_test/import` is unauthenticated, takes that entire object, atomically replaces all service state, and returns `204`. | §10 | behaviour |
| R-1-202 | Import accepts an unchanged export produced by this service with no dependency on the source process, files, volume, port or network address. | §10 | behaviour |
| R-1-203 | Import is replacement, not merge: it removes all previous destination data and credentials, and repeating the same import restores the same state without duplicating anything. | §10 | behaviour |
| R-1-204 | An import body that does not parse is `400 malformed_request`; a missing field, a `track` other than `pocketful`, a `format_version` other than `1`, or an invalid `state` is `422 validation_failed`; in every failure case the destination state is unchanged. | §10, §5 | error |
| R-1-205 | Export/import preserves accounts and hashed-password login, every existing bearer token, the currency and `minor_units`, all balances, all payments, all requests with their statuses, settlement operator permissions and settlement membership. | §10, §11 | behaviour |
| R-1-206 | Export/import preserves every completed idempotent request body together with its original response status and body, so a retry after import returns the original response; keys whose original request failed with 4xx remain reusable after import. | §10 | behaviour |
| R-1-207 | Import regenerates no identity, timestamp or monetary record, and never replays seeded or exported payments against an already-net balance; balances after import equal balances at export exactly. | §10 | invariant |
| R-1-208 | Export is an atomic, read-only snapshot: writes on the source after the export returns do not change the exported document, and export changes no state. | §10 | behaviour |
| R-1-209 | `POST /_test/reset` clears all state including imported state. | §10 | behaviour |
| R-1-210 | Replacing destination state with a fresh fixture does not satisfy import: receipts, tokens and retry identity carried in the export must be live in the destination. | §10 | behaviour |

## O. Atomic net settlements

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-220 | The fixture field `settlement_operator_ids` is an array of user ids defaulting to `[]`; those users are settlement operators. | §11 | behaviour |
| R-1-221 | `POST /settlements` requires an idempotency key and a settlement operator: no/unknown token is `401 unauthenticated`; an authenticated non-operator is `403 forbidden`. | §11 | error |
| R-1-222 | Operator permission grants only settlement execution: it gives no access to another user's requests and no visibility of another user's `private` activity items. | §11 | behaviour |
| R-1-223 | The body is `{"transfers":[{"from_handle","to_handle","amount","note","visibility"}…]}` with 1 to 32 entries; each entry follows ordinary payment `amount`, `note` and `visibility` rules, defaulting to empty note and `public`. | §11 | behaviour |
| R-1-224 | A malformed batch shape — `transfers` absent, not an array, empty, or longer than 32 — is `422 validation_failed` (not `400`). | §11 | error |
| R-1-225 | Per-entry errors: an unknown handle is `404 not_found`; a `from_handle` equal to the entry's `to_handle` is `422 self_payment`; an invalid `amount`, `note` or `visibility` is `422 validation_failed`. | §11 | error |
| R-1-226 | Entry errors take precedence in input order — the first entry with any error determines the response — and all entry errors take precedence over `409 insufficient_funds`. | §11 | error |
| R-1-227 | A settlement is affordable when **every** wallet's balance after all of its incoming and outgoing transfers is nonnegative; an unaffordable settlement is `409 insufficient_funds` and changes nothing, even when each transfer would be affordable alone in some order. | §11 | behaviour |
| R-1-228 | Either all movements of a settlement commit together or none do; no intermediate state is observable in which some transfers are applied. | §11 | invariant |
| R-1-229 | A settlement that fails validation or affordability claims no idempotency key and creates no payment and no revision. | §11 | behaviour |
| R-1-230 | A successful settlement returns `201` with `{"settlement_id","committed_at","payments":[…]}`, `payments` in input order and containing every member's full receipt. | §11 | behaviour |
| R-1-231 | Every settlement member is an ordinary payment carrying `settlement_id` linking the batch, `request_id: null`, and a server-assigned `created_at` identical for all members and equal to `committed_at`. | §11 | behaviour |
| R-1-232 | Payments outside a settlement expose `settlement_id: null`. | §11 | behaviour |
| R-1-233 | Replaying a settlement returns `200` with the original complete response and moves no money; `POST /settlements` is the fifth idempotent write path. | §11 | behaviour |
| R-1-234 | Unknown fields inside `transfers` entries and in the settlement body are ignored. | §11, §3.4 | behaviour |
| R-1-235 | A reset or import preserves settlement operator permissions, the original settlement payments, settlement membership and settlement retry responses. | §11, §10 | behaviour |
| R-1-236 | **Decision.** A settlement entry whose `from_handle` or `to_handle` is the operator's own handle is permitted; the `self_payment` rule applies only within one entry (`from_handle == to_handle`). | §11 | behaviour |

## P. Concurrency and load

| id | requirement | spec | kind |
|---|---|---|---|
| R-1-240 | Under 1,000+ concurrent money-moving operations with ~30% exact replays, the conservation invariant (R-1-001), the nonnegativity invariant (R-1-002), the at-most-once invariant (R-1-003) and the no-5xx invariant (R-1-005) all hold. | §1, §5 | invariant |
| R-1-241 | Two concurrent pays of the same `pending` request by the payer with **different** keys result in exactly one `201` payment and one `409 request_not_pending`; money moves once. | §8 | invariant |
| R-1-242 | Two concurrent payments from the same wallet that together exceed its balance cannot both succeed; at least one returns `409 insufficient_funds`. | §1, §8 | invariant |
| R-1-243 | Concurrent settlements and payments touching overlapping wallets remain serializable and conserve the total. | §11 | invariant |
| R-1-244 | A `POST /_test/reset` concurrent with other traffic never produces a 5xx and never leaves a mixed state: after it returns 204, only the new fixture is visible. | §3.3 | invariant |
