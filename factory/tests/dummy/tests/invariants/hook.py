"""Gate hook for the dummy service: the value equals the sum of applied adds."""
import threading

import httpx

UI_ROUTES = ["/"]


def setup(base_url):
    httpx.post(f"{base_url}/reset", json={"value": 0}, timeout=10)
    return {"expected": 0, "applied": set(), "lock": threading.Lock()}


def operation(base_url, ctx, i, rng):
    n = i % 7 + 1
    r = httpx.post(f"{base_url}/add", json={"n": n, "key": f"k{i}"}, timeout=10)
    if r.status_code == 200:
        with ctx["lock"]:
            if i not in ctx["applied"]:
                ctx["applied"].add(i)
                ctx["expected"] += n
    return r.status_code


def invariant(base_url, ctx):
    got = httpx.get(f"{base_url}/value", timeout=10).json()["value"]
    return got == ctx["expected"], f"value {got}, expected {ctx['expected']}"


def populate(base_url):
    setup(base_url)
    for i in range(5):
        httpx.post(f"{base_url}/add", json={"n": i + 1}, timeout=10)


def snapshot(base_url):
    return httpx.get(f"{base_url}/value", timeout=10).json()


def carry(old_url, new_url):
    httpx.post(f"{new_url}/reset", json=snapshot(old_url), timeout=10)
