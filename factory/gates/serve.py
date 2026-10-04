"""Start a stage folder's service exactly as the gates do (offline, 2 vCPU,
2 GiB) and print its base URL, for attacking or exploring it by hand.

    python -m factory.gates.serve stage-<N>          # prints URL and the stop command
    python -m factory.gates.serve --stop <container> <network>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from factory.gates.common import GateError, Service, run


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("stage_dir", nargs="?", type=Path)
    parser.add_argument("--stop", nargs=2, metavar=("CONTAINER", "NETWORK"))
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--commit", help="serve this commit (built from a private worktree)")
    args = parser.parse_args(argv)
    if args.stop:
        run(["docker", "rm", "-f", args.stop[0]])
        run(["docker", "network", "rm", args.stop[1]])
        print("stopped")
        return 0
    if not args.stage_dir:
        parser.error("give a stage folder or --stop")
    folder, worktree, root = args.stage_dir.resolve(), None, None
    if args.commit:
        from factory.gates.common import repo_root
        from factory.gates.run import checkout
        root = repo_root(folder)
        worktree = checkout(root, args.commit)
        folder = worktree / args.stage_dir.resolve().relative_to(root)
    service = Service(folder, None, args.health_path, tag=f"redline-serve-{args.stage_dir.resolve().name}")
    try:
        service.build()
        url = service.start()
    except GateError as exc:
        service.stop()
        print(f"could not start: {exc}", file=sys.stderr)
        return 1
    finally:
        if worktree:  # the image holds the files; the worktree can go
            run(["git", "-C", str(root), "worktree", "remove", "--force", str(worktree)])
    print(f"BASE_URL={url}")
    print(f"stop: python -m factory.gates.serve --stop {service.container[:12]} {service.network}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
