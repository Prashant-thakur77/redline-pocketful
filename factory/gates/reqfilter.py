"""pytest plugin: keep only the tests that name one of the given requirement ids
(in the test's name or the first line of its docstring), so a work item can be
checked against its own requirements while the rest of the stage is unbuilt.

    pytest -p factory.gates.reqfilter --req R-1-001,R-1-002 tests/
"""
from __future__ import annotations

import re


def pytest_addoption(parser):
    parser.addoption("--req", default="", help="comma-separated requirement ids to keep")


def _variants(req: str) -> set[str]:
    base = req.strip().lower()
    return {base, base.replace("-", "_")}


def names_requirement(item, wanted: set[str]) -> bool:
    doc = (getattr(getattr(item, "function", None), "__doc__", None) or "").strip().splitlines()
    text = f"{item.name} {doc[0] if doc else ''}".lower()
    return any(re.search(rf"(?<![0-9a-z]){re.escape(w)}(?![0-9])", text) for w in wanted)


def pytest_collection_modifyitems(config, items):
    reqs = [r for r in config.getoption("--req").split(",") if r.strip()]
    if not reqs:
        return
    wanted = set().union(*(_variants(r) for r in reqs))
    keep, drop = [], []
    for item in items:
        (keep if names_requirement(item, wanted) else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
    items[:] = keep
