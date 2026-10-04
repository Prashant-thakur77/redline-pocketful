"""One self-contained HTML page per stage: gates, verdicts, rejections, cost.

Adapted from Freight Room's audit dossier: built only from the record (the
ledger), and every figure shows where it came from.
"""
from __future__ import annotations

import html
from pathlib import Path

from factory import metrics
from factory.events import Event, now
from factory.ledger import Ledger

STYLE = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--ok:#1f7a4d;--bad:#b42318}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#eceae4;--muted:#a3a198;--line:#33322e;--ok:#4cc38a;--bad:#ff6b5b}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:0 auto;padding:24px 16px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 8px}
.muted{color:var(--muted)}table{border-collapse:collapse;width:100%;font-size:14px;display:block;overflow-x:auto}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.pass{color:var(--ok);font-weight:600}.fail{color:var(--bad);font-weight:600}
.src{font:12px ui-monospace,monospace;color:var(--muted)}
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _src(sources: list[str]) -> str:
    shown = ", ".join(sources[:3]) + (f" +{len(sources) - 3}" if len(sources) > 3 else "")
    return f'<span class="src">{_e(shown or "no record")}</span>'


def render(events: list[Event], stage: int, ledger_ok: tuple[bool, str], repo: Path | None = None) -> str:
    from factory.report import change_forced

    rows = metrics.for_stage(events, stage)
    gates = metrics.gate_sheet(rows)
    costs = metrics.cost_by_seat(rows)
    rejected = metrics.rejections(rows)
    catch = metrics.catch_rate(rows)
    closed = next((e for e in reversed(rows) if e.kind == "stage_closed"), None)

    gate_html = "".join(
        f"<tr><td>{_e(g)}</td><td class='{r['last']}'>{_e(r['last'])}</td><td>{r['runs']}</td>"
        f"<td>{r['failures']}</td><td>{_src(r['sources'])}</td></tr>" for g, r in gates.items())
    cost_html = "".join(
        f"<tr><td>{_e(seat)}</td><td>{int(m['tokens'].value):,}</td><td>${m['usd'].value:,.2f}</td>"
        f"<td>{m['seconds'].value / 60:.1f}</td><td>{_src(m['tokens'].sources)}</td></tr>"
        for seat, m in sorted(costs.items()))
    reject_html = "".join(
        f"<tr><td>{_e(r['node'])}</td><td>{_e(r['seat'])}</td><td class='fail'>{_e(r['verdict'])}</td>"
        f"<td>{_e(r['what'])}</td><td>{_e(change_forced(repo, r['commit'], r['fixed_commit']) if r['recovered_by'] else 'not recovered')}</td>"
        f"<td>{_src([r['source']])}</td></tr>" for r in rejected)
    chain = "intact" if ledger_ok[0] else f"BROKEN ({ledger_ok[1]})"
    outcome = _e(closed.payload.get("result")) if closed else "open"

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Stage {stage} dossier</title>
<style>{STYLE}</style></head><body>
<h1>Stage {stage} dossier</h1>
<p class="muted">Outcome: <b>{outcome}</b> · catch rate {catch.value:.0%} · ledger chain {chain} · generated {now()}</p>
<h2>Gates</h2><table><tr><th>Gate</th><th>Last</th><th>Runs</th><th>Failures caught</th><th>Source</th></tr>{gate_html or "<tr><td colspan=5>no gate runs</td></tr>"}</table>
<h2>Reviews that changed the work</h2><table><tr><th>Node</th><th>Seat</th><th>Verdict</th><th>What it caught</th><th>Change it forced</th><th>Source</th></tr>{reject_html or "<tr><td colspan=6>none</td></tr>"}</table>
<h2>Cost by seat</h2><table><tr><th>Seat</th><th>Tokens</th><th>USD</th><th>Minutes</th><th>Source</th></tr>{cost_html or "<tr><td colspan=5>no cost records</td></tr>"}</table>
</body></html>"""


def build(ledger_path: Path | str, out_dir: Path | str, repo: Path | None = None) -> list[Path]:
    ledger = Ledger(ledger_path)
    events = ledger.events()
    ok = ledger.verify()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for stage in sorted({e.stage for e in events if e.stage is not None}):
        path = out / f"stage-{stage}.html"
        path.write_text(render(events, stage, ok, repo))
        written.append(path)
    return written


if __name__ == "__main__":
    import sys

    for p in build(*(sys.argv[1:3] or ["evidence/ledger.jsonl", "evidence/dossier"])):
        print(p)
