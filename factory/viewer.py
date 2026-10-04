"""One self-contained page that replays a run from its real record: the room log
and the ledger. Nothing is curated or invented; every row is a room message.

    python -m factory.viewer --room room.json --ledger evidence/ledger.jsonl [--repo .] --out evidence/run.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from pathlib import Path

from factory import metrics, roomlog
from factory.ledger import Ledger
from factory.protocol import try_parse

PALETTE = ["#5b8def", "#d9822b", "#2f9e6e", "#c2417a", "#7a5af8", "#0f8fa3", "#8a6d1f"]
VERDICT_CLASS = {"GO": "ok", "HOLDS": "ok", "READY": "info", "NEEDS_WORK": "warn", "BLOCK": "bad", "BREACH": "bad"}

STYLE = """
:root{--bg:#f7f6f2;--panel:#fff;--fg:#1c1c1a;--muted:#6b6a64;--line:#e3e0d7;--ok:#1f7a4d;--warn:#a15c07;--bad:#b42318;--info:#2f5fd0;--chip:#f0eee8}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#121211;--panel:#1b1b19;--fg:#ecebe6;--muted:#a19f97;--line:#2f2e2a;--ok:#4cc38a;--warn:#f0a640;--bad:#ff6b5b;--info:#7aa2ff;--chip:#262522}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:26px;margin:0}h2{font-size:17px;margin:32px 0 10px}.muted{color:var(--muted)}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:18px 0}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.kpi b{display:block;font-size:24px}.kpi span{color:var(--muted);font-size:13px}
.steps{display:flex;gap:8px;flex-wrap:wrap}.step{padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:var(--panel);font-size:13px}
.step.closed{border-color:var(--ok);color:var(--ok)}.step.partial{border-color:var(--warn);color:var(--warn)}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0 14px}
.filters button{font:inherit;font-size:13px;min-height:36px;padding:4px 12px;border-radius:999px;border:1px solid var(--line);background:var(--panel);color:var(--fg);cursor:pointer}
.filters button[aria-pressed=true]{background:var(--fg);color:var(--bg)}
button:focus-visible,summary:focus-visible{outline:2px solid var(--info);outline-offset:2px}
ol.timeline{list-style:none;margin:0;padding:0;border-left:2px solid var(--line)}
.msg{position:relative;margin:0 0 12px 14px;padding:10px 14px;background:var(--panel);border:1px solid var(--line);border-radius:10px}
.msg::before{content:"";position:absolute;left:-21px;top:16px;width:10px;height:10px;border-radius:50%;background:var(--dot)}
.head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}.seat{font-weight:600;color:var(--dot)}.to,.time{color:var(--muted);font-size:13px}
.text{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere}
details summary{cursor:pointer;color:var(--info);font-size:13px;margin-top:4px}
.chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}.chip{background:var(--chip);border-radius:6px;padding:2px 8px;font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
.v{font-weight:700}.v.ok{color:var(--ok)}.v.warn{color:var(--warn)}.v.bad{color:var(--bad)}.v.info{color:var(--info)}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line);vertical-align:top}
.scroll{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:10px}
footer{margin-top:40px;color:var(--muted);font-size:13px}
@media (max-width:640px){.cards tr:first-child{display:none}.cards tr{display:block;border-bottom:1px solid var(--line);padding:8px 0}
.cards td{display:flex;gap:10px;border:0;padding:3px 12px}.cards td::before{content:attr(data-label);color:var(--muted);min-width:96px;flex:none}}
"""

SCRIPT = """
const buttons=[...document.querySelectorAll('.filters button')];
buttons.forEach(b=>b.addEventListener('click',()=>{buttons.forEach(x=>x.setAttribute('aria-pressed',x===b));
const f=b.dataset.filter;document.querySelectorAll('.msg').forEach(m=>{
m.hidden=!(f==='all'||(f==='verdicts'&&m.dataset.verdict)||m.dataset.seat===f);});}));
"""


def _e(text) -> str:
    return html.escape("" if text is None else str(text))


def render(messages: list[roomlog.Message], events, repo: Path | None = None, title: str = "Run") -> str:
    from factory.report import change_forced

    names = roomlog.seat_names(messages)
    seats = sorted(set(names.values()))
    colour = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(seats)}
    said = [m for m in messages if m.kind == "text"]
    first_human = next((i for i, m in enumerate(said) if not m.agent), None)
    human_after = sum(1 for m in said[(first_human or 0) + 1:] if not m.agent) if first_human is not None else 0
    verdicts = Counter()
    rows = []
    for m in said:
        ev = try_parse(m.content) if m.agent else None
        text = re.sub(r"```json[\s\S]*?```", "", m.content)
        text = roomlog.MENTION.sub(lambda x: "@" + names.get(x.group(1), "human").lower(), text).strip()
        to = sorted({names.get(i, "human") for i in m.mentions} - {m.sender})
        chips = ""
        if ev:
            verdicts[ev.verdict] += 1
            chips = (f'<div class="chips"><span class="chip v {VERDICT_CLASS.get(ev.verdict, "")}">{_e(ev.verdict)}</span>'
                     f'<span class="chip">{_e(", ".join(ev.req[:4]))}{"…" if len(ev.req) > 4 else ""}</span>'
                     f'<span class="chip">commit {_e(ev.commit[:8])}</span>'
                     f'<span class="chip">exit {ev.result.exit} · {ev.result.passed} passed · {ev.result.failed} failed</span>'
                     + (f'<span class="chip">{ev.cost.tokens:,} tok · ${ev.cost.usd:.2f}</span>' if ev.cost.tokens or ev.cost.usd else "")
                     + "</div>")
        short, rest = (text[:420], text[420:]) if len(text) > 520 else (text, "")
        body = f'<p class="text">{_e(short)}</p>' + (f"<details><summary>Show the full message</summary>"
                                                     f'<p class="text">{_e(rest)}</p></details>' if rest else "")
        who = m.sender if m.agent or m.sender.lower() == "human" else f"{m.sender} (human)"
        rows.append(f'<li class="msg" data-seat="{_e(m.sender if m.agent else "human")}" '
                    f'data-verdict="{_e(ev.verdict if ev else "")}" style="--dot:{colour.get(m.sender, "var(--muted)")}">'
                    f'<div class="head"><span class="seat">{_e(who)}</span>'
                    f'<span class="to">→ {_e(", ".join("@" + t.lower() for t in to) or "room")}</span>'
                    f'<span class="time">{_e(m.ts[:19].replace("T", " "))}</span></div>{body}{chips}</li>')
    stages = sorted({e.stage for e in events if e.stage is not None})
    steps = "".join(
        f'<span class="step {(c.payload.get("result") if c else "open")}">Stage {s}: '
        f'{_e(c.payload.get("result") if c else "open")}</span>'
        for s in stages for c in [next((e for e in reversed(events) if e.kind == "stage_closed" and e.stage == s), None)])
    rej = metrics.rejections(events)
    def clean(text: str) -> str:
        return re.sub(r"@\[\[[^\]]+\]\]\s*", "", text or "").replace("`", "")

    rej_rows = "".join(
        f"<tr><td data-label='Stage'>{r['stage']}</td><td data-label='Item'>{_e(r['node'] or '—')}</td>"
        f"<td data-label='By'>{_e(r['seat'])}</td>"
        f"<td data-label='Verdict' class='v {VERDICT_CLASS.get(r['verdict'], '')}'>{_e(r['verdict'])}</td>"
        f"<td data-label='Caught'>{_e(clean(r['what'])[:160])}</td>"
        f"<td data-label='Forced'>{_e(clean(change_forced(repo, r['commit'], r['fixed_commit'])) if r['recovered_by'] else 'not recovered')}</td></tr>"
        for r in rej)
    filters = "".join(f'<button type="button" data-filter="{_e(s)}" aria-pressed="false">{_e(s)}</button>' for s in seats)
    span = f"{said[0].ts[:16].replace('T', ' ')} → {said[-1].ts[:16].replace('T', ' ')}" if said else ""
    kpis = [(len(said), "messages in the room"), (len(seats), "seats that spoke"),
            (sum(verdicts[v] for v in ("NEEDS_WORK", "BLOCK", "BREACH")), "rejections"),
            (verdicts["GO"], "GO verdicts"), (human_after, "human messages after the dispatch")]
    kpi_html = "".join(f'<div class="kpi"><b>{n}</b><span>{_e(label)}</span></div>' for n, label in kpis)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{_e(title)}</title><style>{STYLE}</style></head>
<body><main><h1>{_e(title)}</h1><p class="muted">Replay of the real room log and ledger · {_e(span)}</p>
<div class="kpis">{kpi_html}</div>
<h2>Stages</h2><div class="steps">{steps or '<span class="step">no stage closed yet</span>'}</div>
<h2>Reviews that changed the work</h2><div class="scroll"><table class="cards"><tr><th>Stage</th><th>Item</th><th>By</th><th>Verdict</th><th>What it caught</th><th>Change it forced</th></tr>
{rej_rows or '<tr><td colspan=6>none recorded</td></tr>'}</table></div>
<h2>Room</h2><div class="filters" role="group" aria-label="Filter messages">
<button type="button" data-filter="all" aria-pressed="true">All</button>
<button type="button" data-filter="verdicts" aria-pressed="false">Evidence only</button>{filters}</div>
<ol class="timeline">{"".join(rows)}</ol>
<footer>Generated by <code>python -m factory.viewer</code> from the room log and a ledger whose hash chain is checked by <code>python -m factory.ledger</code>.</footer>
</main><script>{SCRIPT}</script></body></html>"""


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--room", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=Path("evidence/ledger.jsonl"))
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--title", default="Redline run")
    parser.add_argument("--out", type=Path, default=Path("evidence/run.html"))
    args = parser.parse_args(argv)
    page = render(roomlog.load(args.room), metrics.measured_only(metrics.with_inferred_stages(Ledger(args.ledger).events())), args.repo, args.title)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print(f"run viewer -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
