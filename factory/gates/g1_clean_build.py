"""Gate 1 — clean build: RUN.md gives the docker build and run commands, the
folder builds from its Dockerfile, and it serves its health check with no
outbound network, 2 vCPU and 2 GiB, within 60 seconds."""
from __future__ import annotations

from factory.gates.common import Gate, Service, base_parser, failure


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    args = parser.parse_args(argv)
    gate = Gate("g1", args)
    for required in ("Dockerfile", "RUN.md"):
        if not (gate.stage_dir / required).is_file():
            return gate.finish(False, f"{required} is missing")
    run_md = (gate.stage_dir / "RUN.md").read_text(errors="replace")
    if not ("docker build" in run_md and "docker run" in run_md):
        return gate.finish(False, "RUN.md must give the exact `docker build` and `docker run` commands")
    service = Service(gate.stage_dir, gate, args.health_path)
    try:
        service.build()
        url = service.start(args.health_timeout)
        return gate.finish(True, f"built and healthy offline at {url}{args.health_path}")
    except Exception as exc:
        return gate.finish(False, failure(exc))
    finally:
        service.stop()


if __name__ == "__main__":
    raise SystemExit(main())
