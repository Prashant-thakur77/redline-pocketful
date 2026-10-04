"""Turn the run record into the numbers FACTORY.md quotes, plus the dossier.

    python -m factory.report [--room room.json] [--repo .] [--inject FACTORY.md]
    python -m factory.report --summary          # short text for the final report

Sources: the hash-chained ledger (gates, verdicts, costs), the room log (who
talked to whom) and git history (who committed what). Nothing is typed by hand.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from factory import dossier, metrics, roomlog
from factory.events import Event
from factory.ledger import Ledger

START, END = "<!-- report:start -->", "<!-- report:end -->"


def latest(events: list[Event], stage: int, gate: str) -> Event | None:
    found = [e for e in events if e.kind == "gate_result" and e.stage == stage and e.payload.get("gate") == gate]
    return found[-1] if found else None


def gate_cell(e: Event | None, fmt) -> str:
    if e is None:
        return "—"
    return ("✅ " if e.payload.get("passed") else "❌ ") + fmt(e.payload)


def stage_rows(events: list[Event]) -> list[str]:
    stages = sorted({e.stage for e in events if e.stage is not None})
    rows = ["| Stage | Outcome | Spec tests | Storm | Mutation | Public checks | UI | Regression | Rejections |",
            "|---|---|---|---|---|---|---|---|---|"]
    for s in stages:
        mine = metrics.for_stage(events, s)
        closed = next((e for e in reversed(mine) if e.kind == "stage_closed"), None)
        rej = metrics.rejections(mine)
        rows.append("| " + " | ".join([
            str(s), closed.payload.get("result", "closed") if closed else "open",
            gate_cell(latest(events, s, "g2"), lambda p: f"{p.get('counts', {}).get('passed', 0)}/"
                                                         f"{p.get('counts', {}).get('tests', 0)}"),
            gate_cell(latest(events, s, "g4"), lambda p: f"{p.get('ops', 0)} ops"),
            gate_cell(latest(events, s, "g6"), lambda p: f"{p.get('score', 0):.0%} killed"),
            gate_cell(latest(events, s, "g3"), lambda p: f"claims {p.get('claimed', 'none')}"),
            gate_cell(latest(events, s, "g7"), lambda p: f"{len(p.get('screenshots', []))} shots"),
            gate_cell(latest(events, s, "g5"), lambda p: ", ".join(p.get("earlier", [])) or "first stage"),
            f"{len(rej)} ({sum(1 for r in rej if r['recovered_by'])} recovered)"]) + " |")
    return rows


def cost_rows(events: list[Event]) -> list[str]:
    rows = ["| Stage | Seat | Tokens | USD (list price) | Seat minutes |", "|---|---|---:|---:|---:|"]
    totals = defaultdict(float)
    for s in sorted({e.stage for e in events if e.kind == "cost"}, key=lambda x: (x is None, x)):
        for seat, m in sorted(metrics.cost_by_seat(metrics.for_stage(events, s)).items()):
            tokens = f"{int(m['tokens'].value):,}" if m["tokens"].value else "—"
            rows.append(f"| {s if s is not None else '—'} | {seat} | {tokens} | "
                        f"${m['usd'].value:,.2f} | {m['seconds'].value / 60:,.1f} |")
            for k in ("tokens", "usd", "seconds"):
                totals[k] += m[k].value
    total_tokens = f"{int(totals['tokens']):,}" if totals["tokens"] else "—"
    rows.append(f"| **all** | **all** | **{total_tokens}** | **${totals['usd']:,.2f}** | "
                f"**{totals['seconds'] / 60:,.1f}** |")
    return rows


def change_forced(repo: Path | None, before: str | None, after: str | None) -> str:
    """What the rejection made the band change: the diff from the rejected commit to the accepted one."""
    if not (repo and before and after):
        return "—"
    proc = subprocess.run(["git", "-C", str(repo), "diff", "--shortstat", before, after, "--", ".", ":!evidence"],
                          capture_output=True, text=True)
    stat = proc.stdout.strip()
    return (f"`{before[:7]}→{after[:7]}` " + re.sub(r" changed|insertions?|deletions?|\(|\)", "", stat)).strip() if stat else "—"


def rejection_rows(events: list[Event], repo: Path | None = None) -> list[str]:
    rows = ["| Stage | Item | Verdict by | Verdict | What it caught | Change it forced | Source |",
            "|---|---|---|---|---|---|---|"]
    for r in metrics.rejections(events):
        what = re.sub(r"\s+", " ", re.sub(r"@\[\[[^\]]+\]\]\s*", "", r["what"])).replace("|", "/")[:140]
        forced = change_forced(repo, r["commit"], r["fixed_commit"]) if r["recovered_by"] else "not recovered"
        rows.append(f"| {r['stage']} | {r['node'] or '—'} | {r['seat']} | {r['verdict']} | {what} | {forced} | `{r['source']}` |")
    return rows if len(rows) > 2 else rows + ["| — | — | — | — | none recorded | — | — |"]


def gate_rows(events: list[Event]) -> list[str]:
    rows = ["| Gate | Runs | Failures caught | Last |", "|---|---:|---:|---|"]
    for gate, r in metrics.gate_sheet(events).items():
        rows.append(f"| {gate} | {r['runs']} | {r['failures']} | {r['last']} |")
    return rows


def teamwork_rows(room: Path | None, repo: Path | None) -> list[str]:
    said, edges, commits = Counter(), Counter(), Counter()
    if room and room.is_file():
        messages = roomlog.load(room)
        names = roomlog.seat_names(messages)
        for m in messages:
            if m.agent and m.kind == "text":
                said[m.sender] += 1
                for target in set(m.mentions) - {m.sender_id}:
                    if target in names:
                        edges[(m.sender, names[target])] += 1
    if repo:
        proc = subprocess.run(["git", "-C", str(repo), "log", "--format=%an"], capture_output=True, text=True)
        commits.update(line for line in proc.stdout.splitlines() if line)
    if not (said or commits):
        return ["No room log or history given."]
    seats = sorted(set(said) | set(commits))
    rows = ["| Seat | Messages | Commits |", "|---|---:|---:|"]
    rows += [f"| {s} | {said.get(s, 0)} | {commits.get(s, 0)} |" for s in seats]
    if edges:
        pairs = sum(1 for (a, b) in edges if (b, a) in edges) // 2
        rows += ["", f"Direct @handle handoffs: {sum(edges.values())} across {len(edges)} seat pairs; "
                     f"{pairs} pair(s) talked in both directions."]
    return rows


def backed_go(events: list[Event]) -> str:
    """How many GO verdicts the gate results actually support (stated even when it is not all)."""
    from factory.record import go_blockers
    gos = [e for e in events if metrics.verdict_of(e) == "GO" and e.node]
    backed = [e for e in gos if not go_blockers([x for x in events if x.ts <= e.ts], e.stage, e.node,
                                                 str(e.payload.get("commit") or "") or None)]
    return f"{len(backed)} of {len(gos)} GO verdicts are backed by passing gate results on the commit judged."


def build(events: list[Event], chain: tuple[bool, str], room: Path | None, repo: Path | None) -> str:
    catch = metrics.catch_rate(events)
    reviewed = {(e.stage, e.node) for e in events if metrics.verdict_of(e) and e.node}
    rework = len(metrics.rejections(events)) / len(reviewed) if reviewed else 0
    parts = [
        "### Results per stage", *stage_rows(events), "",
        "### Cost and time", *cost_rows(events), "",
        f"Wall time covered by the ledger: {metrics.wall_seconds(events) / 3600:.1f} h.", "",
        "### Catches and recovery", *rejection_rows(events, repo), "",
        f"Catch rate {catch.value:.0%} of reviewed items were rejected at least once; "
        f"rework {rework:.2f} rejections per reviewed item. {backed_go(events)}", "",
        "### What each gate caught", *gate_rows(events), "",
        "### Who did the work", *teamwork_rows(room, repo), "",
        f"_Generated by `python -m factory.report` from {len(events)} ledger events; "
        f"hash chain {'intact' if chain[0] else 'BROKEN: ' + chain[1]}._",
    ]
    return "\n".join(parts) + "\n"


def summary(events: list[Event]) -> str:
    lines = []
    for s in sorted({e.stage for e in events if e.stage is not None}):
        mine = metrics.for_stage(events, s)
        closed = next((e for e in reversed(mine) if e.kind == "stage_closed"), None)
        gates = {g: ("pass" if r["last"] == "pass" else "fail") for g, r in metrics.gate_sheet(mine).items()}
        usd = sum(m["usd"].value for m in metrics.cost_by_seat(mine).values())
        lines.append(f"stage {s}: {closed.payload.get('result') if closed else 'open'}; gates {gates}; "
                     f"rejections {len(metrics.rejections(mine))}; spend ${usd:,.2f}")
    for r in metrics.rejections(events):
        lines.append(f"  {r['verdict']} stage {r['stage']} item {r['node']}: {r['what'][:100]} "
                     f"(recovered: {'yes' if r['recovered_by'] else 'no'})")
    return "\n".join(lines) or "no events yet"


def inject(path: Path, body: str):
    text = path.read_text()
    if START not in text or END not in text:
        raise ValueError(f"{path} has no {START} … {END} block")
    head, rest = text.split(START, 1)
    path.write_text(head + START + "\n" + body + rest[rest.index(END):])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", type=Path, default=Path("evidence/ledger.jsonl"))
    parser.add_argument("--room", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--out", type=Path, default=Path("evidence/report.md"))
    parser.add_argument("--dossier", type=Path, default=Path("evidence/dossier"))
    parser.add_argument("--inject", type=Path, help="replace the report block in this file")
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    ledger = Ledger(args.ledger)
    events = metrics.measured_only(metrics.with_inferred_stages(metrics.chronological(ledger.events())))
    if args.summary:
        print(summary(events))
        return 0
    body = build(events, ledger.verify(), args.room, args.repo)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body)
    pages = dossier.build(args.ledger, args.dossier, args.repo)
    if args.inject:
        inject(args.inject, body)
    print(f"report -> {args.out}; dossier pages: {len(pages)}" + (f"; injected into {args.inject}" if args.inject else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
