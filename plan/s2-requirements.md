# Stage 2 requirements — pocketful: wallet screens and payment authorizations

Source of truth: `/home/prashant/projects/dark-factory-wearedevs/pocketful/spec/stage-2.md`.
`§` references are to `stage-1.md` unless prefixed `s2`.

**Every requirement in `plan/s1-requirements.md` (R-1-001 … R-1-244) continues to apply
unchanged in `stage-2/`, except where a row below explicitly amends one.** Amendments:
R-1-120 (`GET /me` gains fields), R-1-133 / R-1-158 / R-1-227 (funds checks now against
`available`), R-1-100 (seven idempotent write paths), R-1-042/R-1-045 (fixture gains
`authorization_ttl_seconds` and `authorizations`).

## A. Invariants — stage 2 adds three; stage 1's seven still hold

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-001 | The sum of all wallet `total` values always equals the total seeded by the last reset (or import). A hold moves no money; only payments, settlements and captures transfer money between wallets. | s2 §1 | invariant |
| R-2-002 | `available = total − held` is never negative, at any read and transiently. Held funds cannot fund new payments, new authorizations or settlement net debits. Captures may spend the money reserved for them. | s2 §2 | invariant |
| R-2-003 | Cumulative captures on an authorization never exceed its authorized `amount`; each idempotent capture moves money once; a closed hold can never be captured again. | s2 §3 | invariant |
| R-2-004 | `held` always equals the sum of `remaining_amount` over the caller's `open`, unexpired authorizations where the caller is the payer; it never counts incoming authorizations. | s2 §Model, §API | invariant |
| R-2-005 | A hold is released exactly once: by final capture, by void, or by expiry — never twice, so no wallet's `available` ever exceeds its `total`. | s2 §Authorizations | invariant |

## B. API changes to stage-1 endpoints

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-010 | `GET /me` returns `{"user_id","display_name","handle","balance","total","available","held","currency","minor_units"}`; `balance` and `total` are always equal, `held` is the sum of open holds, and `available` is `total − held`, never negative. | s2 §API | behaviour |
| R-2-011 | With no open holds, `balance`, `total` and `available` agree, `held` is `0`, and every stage-1 behaviour is bit-for-bit unchanged. | s2 §API | behaviour |
| R-2-012 | `POST /payments` remains an immediate transfer; it never leaves an intermediate hold and never requires a separate capture. | s2 §API | behaviour |
| R-2-013 | Every stage-1 `409 insufficient_funds` — on `POST /payments`, `POST /requests/{id}/pay` and `POST /settlements` — is now evaluated against `available` rather than `total`. With no open holds the outcome is unchanged. | s2 §API | behaviour |
| R-2-014 | Paying a request remains immediate; authorizing a request is out of scope and no endpoint creates a hold from a request. | s2 §API | behaviour |
| R-2-015 | `POST /splits` is unchanged in every respect. | s2 §API | behaviour |
| R-2-016 | There are seven idempotent write paths: stage 1's five plus `POST /authorizations` and `POST /authorizations/{id}/capture`. All of §7 applies to each independently. | s2 §API | behaviour |
| R-2-017 | A settlement's net debit for a wallet is affordable only against that wallet's `available`; a wallet whose net position is negative beyond its `available` makes the whole settlement `409 insufficient_funds`. | s2 §2, §API | behaviour |
| R-2-018 | The payment object gains `authorization_id`: the authorization for a capture, `null` for every other payment. `request_id` semantics are unchanged, and a capture has `request_id: null`. | s2 §API | behaviour |

## C. Fixture and model

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-020 | The fixture gains `authorization_ttl_seconds`, a positive integer defaulting to `600` when omitted; it applies to every authorization created through the API. A non-positive or non-integer value is `422 validation_failed` from `POST /_test/reset`. | s2 §Model | error |
| R-2-021 | The fixture gains `authorizations`, each `{id, from_user_id, to_user_id, amount, note, visibility, status, expires_at}`. Omitting the array means an empty list, so a stage-1 fixture remains valid. | s2 §Model | behaviour |
| R-2-022 | A seeded authorization carries its own absolute `expires_at` instead of deriving one from the TTL. | s2 §Model | behaviour |
| R-2-023 | A seeded user's `balance` is still `total`. `available` is **derived, never seeded** — the service subtracts the seeded open holds itself. | s2 §Model | behaviour |
| R-2-024 | A user whose seeded unexpired **open** holds sum to more than their `balance` makes `POST /_test/reset` return `422 validation_failed` and change nothing, exactly like a negative seeded balance. | s2 §Model | error |
| R-2-025 | Seeded `status` is one of `open`, `captured`, `voided`, `expired`; only `open` holds funds. A seeded status outside that set is `422 validation_failed`. | s2 §Model | error |
| R-2-026 | Seeded expiry times are at least an hour from reset time, in the past or the future; a seeded `open` authorization whose `expires_at` is already past holds nothing and reads as `expired`. | s2 §Model | behaviour |
| R-2-027 | A seeded authorization referencing an unknown user id, or with `from_user_id == to_user_id`, is `422 validation_failed` from reset. | s2 §Model, §5 | error |
| R-2-028 | **Decision.** A seeded authorization may supply `captured_amount`; when omitted it is `0` for `open`/`voided`/`expired` and the full `amount` for `captured`. A `captured_amount` outside `0..amount` is `422 validation_failed`. | s2 §Model | error |

## D. Expiry

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-030 | An authorization whose `expires_at` is at or before now is `expired` and holds no funds; reads and writes reflect expiry even though no request occurred at the deadline (no background job may be required for correctness, and none may be required for the read to be right). | s2 §Model | behaviour |
| R-2-031 | `GET /authorizations` shows `status: "expired"` for such an authorization, and it never matches `status=open`. | s2 §Model, §API | behaviour |
| R-2-032 | `GET /me` includes the released remainder of an expired authorization in `available` immediately, with no write having occurred. | s2 §Model | behaviour |
| R-2-033 | Expiry of a partially captured authorization releases only the remainder and preserves every capture record and `captured_amount`. | s2 §API | behaviour |
| R-2-034 | Newly created authorizations may have lifetimes shorter than an hour (whatever `authorization_ttl_seconds` says), and expiry must be exact to the instant of `expires_at`: a capture at exactly `expires_at` is `409 authorization_expired`. | s2 §Model, §API | behaviour |

## E. `POST /authorizations`

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-040 | `POST /authorizations` requires `Idempotency-Key`; the caller is the payer. Body `{"to_handle","amount","note","visibility"}` with `note` and `visibility` optional and the same defaults as `POST /payments` (`""`, `"public"`). | s2 §API | behaviour |
| R-2-041 | Success is `201` with `{"authorization_id","from_user_id","from_handle","to_user_id","to_handle","amount","captured_amount","currency","note","visibility","status","expires_at","payment_id","created_at","remaining_amount","payment_ids","closed_at"}`; at creation `captured_amount` is `0`, `status` is `"open"`, `payment_id` is `null`, `payment_ids` is `[]`, `remaining_amount` equals `amount`, `closed_at` is `null`. | s2 §API, s3 §Historical holds | behaviour |
| R-2-042 | `expires_at` is exactly `created_at` plus `authorization_ttl_seconds`. | s2 §API | behaviour |
| R-2-043 | Creating an authorization places a hold: the payer's `held` rises by `amount` and `available` falls by `amount`, while `total` and `balance` are unchanged and no money moves to the receiver. | s2 §1, §API | behaviour |
| R-2-044 | A caller whose `available` is below `amount` gets `409 insufficient_funds`; existing holds therefore block new authorizations. | s2 §API | error |
| R-2-045 | `POST /authorizations` errors: `amount` below 1, above 1000000000 or non-integral → `422 validation_failed`; `to_handle` equal to the caller's handle → `422 self_payment`; `note` over 200 characters or `visibility` not `public`/`private` → `422 validation_failed`; unknown handle → `404 not_found`. Precedence follows R-1-075/R-1-076. | s2 §API | error |
| R-2-046 | An open authorization is **not** a feed item and never appears in `GET /activity`. | s2 §API | behaviour |

## F. `POST /authorizations/{id}/capture`

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-050 | `POST /authorizations/{id}/capture` requires `Idempotency-Key`; only the **receiver** (the `to` party) may capture. | s2 §API | behaviour |
| R-2-051 | Body is `{"amount": <int>, "final": <bool>}`, both optional: `amount` defaults to the authorization's **remaining** amount, `final` defaults to `true`. | s2 §API | behaviour |
| R-2-052 | A replay must send the identical body: `{}` and `{"amount": 2000}` are different JSON values even when they mean the same capture, so reusing one key across them is `409 idempotency_key_reuse`. | s2 §API | error |
| R-2-053 | Success is `201` with the created **payment**, in exactly the `POST /payments` shape, with `authorization_id` set to this authorization and `request_id: null`. The payment's `amount` is the captured amount; its `note` and `visibility` are copied from the authorization. | s2 §API | behaviour |
| R-2-054 | A capture payment appears in `GET /activity` by the ordinary visibility rule (R-1-191). | s2 §API | behaviour |
| R-2-055 | A capture moves money from the payer's wallet to the receiver's and reduces the hold by the captured amount in one atomic step; the payer's `total` falls by the captured amount and the receiver's rises by it. | s2 §1, §API | behaviour |
| R-2-056 | With `final` true (the default) the authorization becomes `captured`, carries cumulative `captured_amount` and `payment_id`, and **releases the uncaptured remainder immediately** — capturing 1500 of 2000 returns 500 to the payer's `available` in the same step. `remaining_amount` becomes `0` and `closed_at` is set. | s2 §API | behaviour |
| R-2-057 | A second capture after a final capture is `409 authorization_not_open`. | s2 §API | error |
| R-2-058 | With `final: false` and a nonzero uncaptured remainder, `status` stays `open`, the remainder stays held, and further captures are allowed up to that remainder. | s2 §API | behaviour |
| R-2-059 | Capturing the entire remainder closes the authorization (`status: "captured"`, `remaining_amount: 0`) even with `final: false`. | s2 §API | behaviour |
| R-2-060 | `422 capture_exceeds_authorization` compares `amount` with the **remaining** amount, not the original amount; an omitted `amount` defaults to that remainder and therefore never triggers it. | s2 §API | error |
| R-2-061 | `captured_amount` is cumulative across captures; `payment_id` is the latest capture; `payment_ids` lists every capture in order; `remaining_amount` is the amount still held and is `0` when closed. | s2 §API | behaviour |
| R-2-062 | Void and expiry can close a partially captured authorization, release only the remainder, and preserve all capture records. | s2 §API | behaviour |
| R-2-063 | The new fields (`final`, `remaining_amount`, `payment_ids`, `closed_at`) do not change idempotency body equality: equality is still the parsed JSON value of the request body (R-1-106). | s2 §API | behaviour |
| R-2-064 | Capture errors and their precedence: unknown authorization → `404 not_found`; caller not the receiver → `403 forbidden`; `expires_at` at or before now → `409 authorization_expired`; status not `open` → `409 authorization_not_open`; `amount` above the remainder → `422 capture_exceeds_authorization`; `amount` below 1 or non-integral, or `final` not boolean → `422 validation_failed`. Field validation (422 validation_failed for malformed `amount`/`final`) precedes lookup per R-1-075; `capture_exceeds_authorization` is evaluated after the state checks because it needs the remainder. | s2 §API | error |
| R-2-065 | **Decision.** When an authorization is both expired by the clock and not `open` by status, `409 authorization_expired` wins for a seeded/API `open` authorization past its deadline, and `409 authorization_not_open` wins for one already `captured` or `voided`. | s2 §API | error |
| R-2-066 | A capture whose money is already reserved never fails for funds: the hold guarantees the payer can pay, so a capture within the remainder never returns `409 insufficient_funds` even if the payer's `available` is zero. | s2 §2 | invariant |

## G. `POST /authorizations/{id}/void`

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-070 | `POST /authorizations/{id}/void` takes no idempotency key and may be called **only by the payer** (the `from` party), releasing their own hold. | s2 §API | behaviour |
| R-2-071 | Success is `200` with the authorization at `status: "voided"`, the hold released, `remaining_amount: 0` and `closed_at` set; `available` rises by the released remainder in the same step. | s2 §API | behaviour |
| R-2-072 | Voiding an already-`voided` authorization is `200` with the current state and releases nothing further. | s2 §API | behaviour |
| R-2-073 | Voiding a `captured` or `expired` authorization is `409 authorization_not_open`. | s2 §API | error |
| R-2-074 | For an existing authorization, capture and void return `403 forbidden` when the caller is not the permitted party, including callers who are neither party; an unknown id is `404 not_found`. | s2 §API | error |
| R-2-075 | Void moves no money and changes no `total`. | s2 §1 | invariant |

## H. `GET /authorizations`

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-080 | `GET /authorizations` returns only authorizations where the caller is the payer or the receiver, and no others, newest first by `created_at`, as `{"authorizations":[…],"has_more":bool}`. | s2 §API | behaviour |
| R-2-081 | `direction=outgoing` selects those where the caller is the payer; `direction=incoming` where the caller is the receiver; absent returns both. An unknown value is `422 validation_failed`. | s2 §API | error |
| R-2-082 | `status` filters to one of `open`, `captured`, `voided`, `expired`; absent returns all. An unknown value is `422 validation_failed`. An authorization expired by the clock matches `expired`, never `open`. | s2 §API | behaviour |
| R-2-083 | `limit`, `offset` and `has_more` behave exactly as on `GET /requests` (R-1-073, R-1-074, R-1-166, R-1-167). | s2 §API | behaviour |
| R-2-084 | The UI and the API share `/authorizations`: HTML is served for `Accept: text/html`, JSON otherwise. | s2 §UI | behaviour |

## I. Browser product — routes and shared paths

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-090 | These routes are reachable by URL: `/` (balance, pay form, request form, activity feed), `/requests`, `/split`, `/signup`, `/login`, `/authorizations`. Every other screen is reachable through the UI. Server- or client-side rendering are both allowed. | s2 §routes | UI |
| R-2-091 | `/requests` and `/authorizations` are shared by browser and API: a request with `Accept: text/html` gets the UI, a request without that header gets JSON. Existing API clients that send no `Accept` or `Accept: application/json` are unaffected. | s2 §routes, §UI | behaviour |
| R-2-092 | Every runtime asset — fonts, scripts, stylesheets, icons — is served from the image; the page makes no external request and renders fully with no outbound network. | §2 | deploy |
| R-2-093 | Navigation is consistent across the required routes and every screen shows the signed-in user. | s2 §Product | UI |

## J. Browser product — formatting and quality

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-100 | A **formatted amount** is the decimal with exactly `minor_units` decimal places, a single space, then the currency code: `100.00 EUR`, `1200 JPY` (no decimal point at all when `minor_units` is `0`), `10.500 BHD`. Balances are never negative, so no sign is shown. | s2 §Formatted amount | UI |
| R-2-101 | Decimal inputs accept amounts as a person would type them and submit minor units: with `minor_units: 2`, `15.00` and `15` both submit `1500` and `15.5` submits `1550`. | s2 §Balance and pay | UI |
| R-2-102 | Nonnumeric input, or more than `minor_units` decimal places, shows the form's error element **without sending a request**: `15.005` is rejected, never rounded. | s2 §Balance and pay | UI |
| R-2-103 | The browser experience reads as a calm, trustworthy consumer finance product with a consistent system for typography, spacing, colour, controls and feedback; primary actions are easy to identify. | s2 §Product | UI |
| R-2-104 | Once holds exist, **`available` is the headline number** and `total` and `held` are visibly secondary. | s2 §Product, §UI | UI |
| R-2-105 | Available, held, pending, loading, successful, refused and uncertain states are visually distinct from one another, not only behaviourally distinct. | s2 §Product | UI |
| R-2-106 | People, amounts and timestamps are formatted for people first; technical identifiers appear only where they help the user. | s2 §Product | UI |
| R-2-107 | Every required flow is clear and usable at a 375 CSS-pixel viewport and at conventional desktop widths (768 px and 1280 px) with **no horizontal page scrolling**. | s2 §Product | UI |
| R-2-108 | Every input has a visible label, keyboard focus is visibly apparent, and text and controls meet sufficient contrast; no serious accessibility violation. | s2 §Product | UI |
| R-2-109 | Considered empty, loading and error states exist for the balance, the activity feed, the request lists and the authorization list. | s2 §Product | UI |
| R-2-110 | No interactive control is smaller than 24 CSS pixels in either dimension at any required viewport. | gate 7 | UI |
| R-2-111 | Demo data seeded through the fixture makes the first screen non-empty: a signed-in seeded user sees a balance, a populated activity feed, and at least one incoming and one outgoing request. | dispatch | UI |

## K. Browser product — `data-testid` contract

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-120 | Signup screen exposes `signup-email`, `signup-password`, `signup-display-name` inputs and `signup-submit`. | s2 §Signup | UI |
| R-2-121 | Login screen exposes `login-email`, `login-password`, `login-submit`. | s2 §Signup | UI |
| R-2-122 | `auth-error` carries the error message and is **present only when there is one**. | s2 §Signup | UI |
| R-2-123 | `current-user` is visible on every screen when signed in, and its text contains the display name. | s2 §Signup | UI |
| R-2-124 | `current-handle` text is **exactly** the caller's handle: no `@`, no surrounding words. | s2 §Signup | UI |
| R-2-125 | `logout-button` is present when signed in and signs the browser out. | s2 §Signup | UI |
| R-2-126 | `wallet-balance` text is exactly the formatted `total` and carries `data-amount="{minor units}"`. | s2 §Balance, §UI | UI |
| R-2-127 | `wallet-available` text is exactly the formatted `available`, carries `data-amount`, and is presented as the headline number. | s2 §UI | UI |
| R-2-128 | `wallet-held` text is exactly the formatted `held` with `data-amount`, and is **absent when `held` is zero**. | s2 §UI | UI |
| R-2-129 | `/` exposes `pay-handle`, `pay-amount` (decimal string), `pay-note`, `pay-visibility` (a select whose option values are exactly `public` and `private`), `pay-submit`, and `pay-error` when the payment is refused — including insufficient funds. | s2 §Balance and pay | UI |
| R-2-130 | `/` exposes `request-handle`, `request-amount`, `request-note`, `request-submit`, and `request-error` when the request is refused. | s2 §Balance and pay | UI |
| R-2-131 | `/` exposes `activity-list` whose children are newest first in the DOM, `empty-activity` shown instead of the list when nothing is visible, and per visible payment: `activity-item-{payment_id}` carrying `data-visibility="public"` or `"private"`, `activity-parties-{payment_id}` whose text contains both handles, `activity-amount-{payment_id}` whose text is exactly the formatted amount, and `activity-note-{payment_id}` whose text is exactly the note and is **present even when the note is empty**. | s2 §Activity feed | UI |
| R-2-132 | Two payments with equal timestamps may appear in either order. | s2 §Activity feed | UI |
| R-2-133 | `/requests` exposes `incoming-list` and `outgoing-list`, `empty-requests` when both are empty, `request-error` when a pay, decline or cancel is refused, and per request `request-item-{request_id}` carrying `data-status="{status}"` and `request-amount-{request_id}` whose text is exactly the formatted amount. | s2 §Requests | UI |
| R-2-134 | `request-pay-{request_id}` and `request-decline-{request_id}` are present **only** on a `pending` **incoming** request; `request-cancel-{request_id}` **only** on a `pending` **outgoing** request. | s2 §Requests | UI |
| R-2-135 | `/split` exposes `split-amount` (decimal, same rule as `pay-amount`), `split-handles` (text input, handles separated by commas, in order), `split-note`, `split-submit`, `split-error`, and `split-preview` containing one `split-share-{handle}` per participant whose text is exactly the formatted share amount. | s2 §Split | UI |
| R-2-136 | `split-preview` shows the shares the server would compute by §9 **before anything is posted**, and the preview and the submitted split have identical shares. | s2 §Split | UI |
| R-2-137 | `/authorizations` exposes `authorization-list` with children newest first in the DOM, `empty-authorizations` when the list is empty, `authorization-error` when a capture or void is refused, and per authorization: `authorization-item-{id}` carrying `data-status="{status}"`, `authorization-amount-{id}` (exactly the formatted authorized amount), `authorization-captured-{id}` (formatted captured amount, **present only when `status` is `captured`**), `authorization-expires-{id}` (text is the RFC 3339 `expires_at`). | s2 §UI | UI |
| R-2-138 | `authorization-capture-amount-{id}` (decimal input pre-filled with the **remaining** amount) and `authorization-capture-{id}` (button) are present **only** on an **incoming** `open` authorization; `authorization-void-{id}` **only** on an **outgoing** `open` authorization. | s2 §UI | UI |
| R-2-139 | `/` exposes the authorize form: `authorize-handle`, `authorize-amount`, `authorize-note`, `authorize-visibility`, `authorize-submit`, with the same input rules as the pay form, and `authorize-error` when the authorization is refused, including insufficient available funds. | s2 §UI | UI |
| R-2-140 | `/` exposes `wallet-refresh`, a button that refreshes the balance and feed **without clearing the pay form**. | s2 §Competing clients | UI |
| R-2-141 | The UI reflects seeded and newly created holds and shows available funds as the spending balance, including immediately after a reset that seeds open holds. | s2 §UI | UI |

## L. Browser behaviour — writes, refresh, and uncertainty

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-150 | The pay form keeps its values after a successful payment. | s2 §Balance and pay | UI |
| R-2-151 | Submitting the unchanged pay form again sends **no second payment**: `wallet-balance` falls once, the feed contains one payment, and `pay-error` is absent. It reuses the same idempotency key and body (§7). | s2 §Balance and pay | invariant |
| R-2-152 | Changing any field of the pay form makes the next submission a new payment with a new key. | s2 §Balance and pay | UI |
| R-2-153 | After any successful action, the balance, the feed and the request lists on the same page show the new state with no manual reload; navigation waits for the write to succeed before refreshing data. Any mechanism, including full navigation, is acceptable. | s2 §Split | UI |
| R-2-154 | **Latest refresh wins:** a delayed earlier read must never overwrite a later refresh, including when responses arrive out of order. | s2 §Competing clients | invariant |
| R-2-155 | When another client has spent the balance, a refused payment shows `pay-error`, refreshes the balance and feed, and preserves **all** pay inputs. | s2 §Competing clients | UI |
| R-2-156 | A request cancelled elsewhere while its pay button is visible shows `request-error` when payment is refused and refreshes the request list so the stale pay button disappears. | s2 §Competing clients | UI |
| R-2-157 | If a payment response is lost — including after `POST /payments` has committed — the UI shows `pay-uncertain` with nonempty text, **not** `pay-error`. An unknown outcome is never presented as a confirmed rejection. | s2 §Competing clients | UI |
| R-2-158 | After `pay-uncertain`, the unchanged form stays retryable with the **same key and the same body**; a successful retry removes both the error and the uncertainty elements, refreshes the balance and feed, and moves money **exactly once**. | s2 §Competing clients | invariant |
| R-2-159 | No background polling, live synchronization, or recovery across page reloads is required; the browser need only refresh after its own action or an explicit refresh. | s2 §Split, §Competing clients | UI |
| R-2-160 | The available and held amounts follow the same refresh rules as the balance. | s2 §Competing clients | UI |

## M. Upgrade from a populated stage-1 state

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-170 | A stage-2 service accepts, unchanged, an export produced by the team's stage-1 service (`track: "pocketful"`, `format_version: 1`) and returns `204`; a stage-1 export with no `authorizations` yields zero holds, so `available == total` for every user. | s2 §Existing clients | behaviour |
| R-2-171 | A browser signed in before the export/import upgrade remains signed in afterwards: its bearer token keeps working with no re-login and no new screen. | s2 §Existing clients | behaviour |
| R-2-172 | Pending requests that existed before the upgrade remain payable through `/requests` after it. | s2 §Existing clients | behaviour |
| R-2-173 | A payment whose response was lost before the export remains retryable after the import with the same body and key; the UI recovers the original payment and refreshes the imported balance, moving money exactly once in total. | s2 §Existing clients | invariant |
| R-2-174 | These upgrade requirements apply when the import completes **between** browser requests; migration during an in-flight request is not required. No page reload is required and the pay form and the pending retry identity survive the upgrade. | s2 §Existing clients | behaviour |
| R-2-175 | A stage-2 export round-trips authorizations, their statuses, `captured_amount`, `payment_ids`, `expires_at`, `closed_at` and `authorization_ttl_seconds`, in addition to everything R-1-205/R-1-206 require. | s2 §Model, §10 | behaviour |

## N. Concurrency

| id | requirement | spec | kind |
|---|---|---|---|
| R-2-180 | Concurrent requests produce the same results as executing them one at a time in some order, and every requirement above holds at every read. | s2 §Concurrent operations | invariant |
| R-2-181 | Two concurrent captures of the same authorization with different keys, each for the full remainder, result in exactly one success; the other is `409 authorization_not_open`. Money moves once. | s2 §3 | invariant |
| R-2-182 | A capture racing a void on the same authorization produces exactly one winner; the hold is released exactly once and `total` is conserved. | s2 §2, §3 | invariant |
| R-2-183 | A payment racing an authorization from the same wallet cannot both succeed when together they exceed `available`. | s2 §2 | invariant |
| R-2-184 | Under a storm of mixed payments, request payments, splits, settlements, authorizations, captures and voids with ~30% replays, R-2-001 … R-2-005 and R-1-001 … R-1-007 all hold. | s2 §Concurrent operations | invariant |
