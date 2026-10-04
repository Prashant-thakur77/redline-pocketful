"""Gate 4 — invariant storm: 1,000+ concurrent operations from the stage's
hook, with a share of them replayed (retries and duplicates, some racing their
original). Any 5xx, transport error or broken invariant fails the gate."""
from __future__ import annotations

import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from factory.gates import hook as hooks
from factory.gates.common import Gate, base_parser, run_gate


def storm(module, base_url: str, ops: int, concurrency: int, replay: float, seed: int, gate: Gate):
    ctx = module.setup(base_url)
    plan = list(range(ops)) + random.Random(seed).sample(range(ops), int(ops * replay))
    random.Random(seed + 1).shuffle(plan)
    statuses, errors, transient_breaks = Counter(), [], []
    done = threading.Event()

    def one(i: int):
        try:
            statuses[module.operation(base_url, ctx, i, random.Random(seed * 1_000_003 + i))] += 1
        except Exception as exc:  # transport errors, timeouts, hook asserts
            errors.append(f"op {i}: {type(exc).__name__}: {str(exc)[:160]}")

    def watch():
        while not done.wait(0.25):
            try:
                ok, why = module.transient(base_url, ctx)
                if not ok:
                    transient_breaks.append(why)
            except Exception as exc:
                transient_breaks.append(f"{type(exc).__name__}: {exc}")

    watcher = threading.Thread(target=watch, daemon=True) if callable(getattr(module, "transient", None)) else None
    started = time.monotonic()
    if watcher:
        watcher.start()
    with ThreadPoolExecutor(concurrency) as pool:
        list(pool.map(one, plan))
    done.set()
    if watcher:
        watcher.join(5)
    elapsed = time.monotonic() - started
    ok, why = module.invariant(base_url, ctx)
    server_errors = sum(n for s, n in statuses.items() if isinstance(s, int) and s >= 500)
    gate.log(f"ops {len(plan)} ({ops} unique, {len(plan) - ops} replays), concurrency {concurrency}, "
             f"{elapsed:.1f}s", f"statuses {dict(statuses)}", *errors[:30], *transient_breaks[:10],
             f"invariant: {ok} — {why}")
    problems = []
    if server_errors:
        problems.append(f"{server_errors} 5xx responses")
    if errors:
        problems.append(f"{len(errors)} transport/hook errors (first: {errors[0]})")
    if transient_breaks:
        problems.append(f"invariant broke mid-storm {len(transient_breaks)}x (first: {transient_breaks[0]})")
    if not ok:
        problems.append(f"invariant broken after storm: {why}")
    stats = {"ops": len(plan), "seconds": round(elapsed, 1), "statuses": {str(k): v for k, v in statuses.items()}}
    return problems, stats


def check(gate: Gate, base_url: str, args) -> int:
    module = hooks.load(gate.stage_dir)
    lacking = hooks.missing(module, "setup", "operation", "invariant")
    if lacking:
        return gate.finish(False, f"hook incomplete: {', '.join(lacking)}")
    problems, stats = storm(module, base_url, args.ops, args.concurrency, args.replay, args.seed, gate)
    detail = "; ".join(problems) or f"invariant held over {stats['ops']} ops in {stats['seconds']}s"
    return gate.finish(not problems, detail, **stats)


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--ops", type=int, default=1000)
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--replay", type=float, default=0.3, help="share of ops sent again")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(argv)
    gate = Gate("g4", args)
    return run_gate(gate, args, lambda url: check(gate, url, args))


if __name__ == "__main__":
    raise SystemExit(main())
