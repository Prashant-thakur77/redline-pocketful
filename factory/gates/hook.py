"""Load a stage's gate hook: `tests/invariants/hook.py`.

The hook is written by the test seat from the dispatched task, so the factory
never knows what is being protected — only how to hammer it:

    setup(base_url) -> ctx
    operation(base_url, ctx, i, rng) -> int      # same i => same request
    invariant(base_url, ctx) -> (bool, str)      # checked when the storm settles
    transient(base_url, ctx) -> (bool, str)      # optional, checked during it: operations are in
                                                 # flight, so read client-side bounds before and
                                                 # after the server read, never a torn snapshot
    populate(base_url) / snapshot(base_url) / carry(old_url, new_url)   # optional
    UI_ROUTES = [...] / ui_login(page, base_url)                        # optional
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

HOOK = Path("tests") / "invariants" / "hook.py"


def load(stage_dir: Path) -> ModuleType | None:
    path = Path(stage_dir) / HOOK
    if not path.is_file():
        return None
    name = f"redline_hook_{abs(hash(str(path.resolve())))}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def missing(module: ModuleType | None, *names: str) -> list[str]:
    if module is None:
        return [str(HOOK)]
    return [n for n in names if not callable(getattr(module, n, None))]
