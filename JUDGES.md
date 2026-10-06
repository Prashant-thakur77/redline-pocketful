# Verify Redline in five minutes

Everything below runs from a fresh clone with Docker and Python 3.12. No BAND account needed.

## 1. The result (2 min)

```
git clone https://github.com/Prashant-thakur77/redline-pocketful && cd redline-pocketful
docker build -t pocketful stage-4 && docker run --rm -p 8080:8080 -e PORT=8080 pocketful
```
Open http://localhost:8080/signup. The same build is live at https://redline-pocketful.onrender.com (free tier: the first request can take about 30 s to wake).

Our own harness run, isolated mode (no outbound network): `evidence/harness/final/summary.json`. Every stage folder claims its own stage, and `stage-4/` passes stages 1, 2, 3 and 4.

## 2. The run (2 min)

- `room.json`: the BAND room the band worked in, exported unedited through the BAND API (4,746 messages). Five of them are from the human: the dispatch and four operator notes, all disclosed in FACTORY.md, Limits.
- `evidence/run.html`: open it in a browser. A replay of the whole run: KPIs, stage stepper, every review that changed the work, a filterable timeline.
- `evidence/ledger.jsonl`: every verdict, gate result, cost line and stage close (3,072 events), hash-chained. Check the chain: `python -m factory.ledger evidence/ledger.jsonl` prints `ok`.
- `git log --format='%an: %s'`: every commit is authored by the seat that made it. `Human` commits are factory tooling and the post-run record only; FACTORY.md, Limits lists them.
- `plan/final-report.md`: the Planner's own closing report, including what was not done.

## 3. The factory (1 min)

- `mandates/*.md`: five generic seat mandates. `python -m factory.genericity factory mandates --exclude factory/tests` checks them and the factory code against a product-noun list and stage-number requirements (add `--kickoff <task repo>` for both tracks' identifiers): 0 hits.
- `proof/toy/`: the same mandates, unchanged, building the other track's toy in a separate room; its stage 1 passes 100% of the toy's stage-1 suite (`proof/toy/harness.txt`, replay `proof/toy/run.html`).
- `FACTORY.md`: how to stand it up, the gates, measured cost per seat and stage, every rejection with the diff it forced, failed experiments, and the limits.

| Claim | Evidence |
|---|---|
| All four stages pass the kickoff harness, isolated | `evidence/harness/final/summary.json` |
| 684 spec tests pass, 0 fail, at the last gate run | `evidence/ledger.jsonl` (gate g2 at `44628bc`), `evidence/gates/s4/` |
| Every gate passed at one commit, mutation 90% | `evidence/ledger.jsonl`, Verifier GO at `d6efb05` (commit `f751f5b`) |
| 913 gate runs, 279 failures stopped before merge | `evidence/report.md`, "What each gate caught" |
| 91 rejections, 18 BREACH verdicts from the Adversary | `evidence/report.md`, "Catches and recovery"; `git log --grep=BREACH` |
| Tests were written before the code | `git log --reverse --format='%h %an %ad' -- stage-1/tests` vs `-- stage-1/service`: Redline's tests (`6663728`) land before any service code |
| Token use measured per turn ($1,187.55 at API list prices; paid via one $200/month subscription, about 20% of a week's limit) | `evidence/report.md`, "Cost and time" (from the seat logs, `factory.ingest --logs`) |
| Generic mandates | `factory.genericity` (0 hits); the same mandates built the toy track, `proof/toy/` |
| The human's role | `room.json` (five human messages), FACTORY.md, Limits |
