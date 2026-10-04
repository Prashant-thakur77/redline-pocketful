# Stage 2 work plan — `stage-2/`

`stage-2/` starts as a copy-forward of the closed `stage-1/`
(`python -m factory.stage_copy stage-1 stage-2`), so every R-1-* requirement is
already satisfied on arrival and must stay satisfied (gate 5).

| id | title | requirements | depends on | seat |
|---|---|---|---|---|
| N2-T | Tests, UI tests and gate hook (incl. `UI_ROUTES`, `ui_login`) from the requirements | all R-2-*, carried R-1-* | — | redline |
| N2-1 | Holds model: `total`/`available`/`held`, fixture `authorizations` + `authorization_ttl_seconds`, reset validation, clock-exact expiry on read | R-2-001…005, R-2-010, R-2-011, R-2-020…028, R-2-030…034 | N2-T | builder |
| N2-2 | `POST /authorizations`, `GET /authorizations`, available-funds checks on every stage-1 funds path | R-2-012…018, R-2-040…046, R-2-080…084 | N2-1 | builder |
| N2-3 | Capture: partial, extended (`final: false`), closing, error precedence; void | R-2-050…066, R-2-070…075 | N2-2 | builder |
| N2-4 | Export/import of holds and the stage-1 upgrade path | R-2-170…175 | N2-3 | builder |
| N2-5 | UI shell: routes, HTML/JSON content negotiation, design system, nav, auth screens, formatting, a11y, responsive 375/768/1280 | R-2-090…093, R-2-100…111, R-2-120…125 | N2-2 | builder |
| N2-6 | `/` screen: wallet numbers, pay form, request form, authorize form, activity feed, `wallet-refresh`, latest-refresh-wins | R-2-126…132, R-2-139, R-2-140, R-2-141, R-2-150…156, R-2-160 | N2-5 | builder |
| N2-7 | `/requests` and `/split` screens incl. client-side share preview | R-2-133…136, R-2-153 | N2-6 | builder |
| N2-8 | `/authorizations` screen: list, capture with prefilled remainder, void | R-2-137, R-2-138 | N2-6, N2-3 | builder |
| N2-9 | Uncertain outcomes: `pay-uncertain`, same-key retry, upgrade-surviving retry identity | R-2-157, R-2-158, R-2-159, R-2-173, R-2-174 | N2-6, N2-4 | builder |
| N2-10 | Hardening: concurrency storm with holds, capture/void races, no-regression against stage 1 | R-2-180…184 | N2-9, N2-7, N2-8 | builder |

Dispatch order: N2-T → N2-1 → N2-2 → N2-3 → (N2-4, N2-5) → N2-6 → (N2-7, N2-8) → N2-9 → N2-10.

Gates per item: `--gates 1,2,4,8`; items touching the browser also need gate 7, so
N2-5 … N2-9 run `--gates 1,2,4,7,8`.

## Gate 7 must be proven non-vacuous at stage 2 (planner, 2026-10-04)

@verifier found that **gate 7 has never run, in any stage-1 pass**: zero `g7` events in
`evidence/ledger.jsonl`, zero `g7` logs in `evidence/gates/s1/`, and no skip record
either — it is simply absent from the gates dict, including in the `--gates all` close run.

For stage 1 that is the correct outcome and my own doing: I told @redline to omit
`UI_ROUTES` from the stage-1 hook because there is no browser product before stage 2, and
`g7_ui --help` documents its route default as "hook `UI_ROUTES` or `/`". A stage-1 service
serves no HTML, so a gate 7 run there would either be skipped or fail on a screen that is
not supposed to exist.

**At stage 2 this becomes the most dangerous gate in the set**, because a gate that records
nothing is indistinguishable from a gate that passed, and R-2-090 … R-2-141 are almost
entirely gate 7's to enforce. Therefore:

- **G7-1.** The stage-2 hook must define `UI_ROUTES` covering every required route — `/`,
  `/requests`, `/split`, `/signup`, `/login`, `/authorizations` — and `ui_login(page, base_url)`,
  so gate 7 visits signed-in screens rather than a login wall at every route.
- **G7-2.** Gate 7 must be run explicitly, not inferred from `--gates all`. It must emit a
  log under `evidence/gates/s2/` and a `g7` event in the ledger.
- **G7-3.** **A missing or empty gate 7 record at stage-2 close is a close failure, not a
  pass.** @verifier must check the `g7` event exists and names the routes it visited before
  issuing any stage-2 GO. A vacuous pass here would let every UI requirement through
  unchecked, which is the exact failure mode this factory exists to prevent.
- **G7-4.** The first stage-2 item that renders a screen (N2-5) must not get a GO until a
  gate 7 run has actually produced screenshots in `evidence/ui/`.
