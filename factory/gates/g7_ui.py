"""Gate 7 — UI quality: every route at 375, 768 and 1280 px wide with no
horizontal overflow, zero serious or critical axe violations, no undersized
controls, no asset fetched from outside the service, and empty/loading/error
states present (marked `data-state`). Screenshots go to evidence/ui/."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from factory.gates import hook as hooks
from factory.gates.common import Gate, base_parser, run_gate

WIDTHS = {375: 812, 768: 1024, 1280: 800}
STATES = {"empty", "loading", "error"}
AXE_VERSION = "4.10.2"
AXE_URL = f"https://cdn.jsdelivr.net/npm/axe-core@{AXE_VERSION}/axe.min.js"
AXE_CACHE = Path.home() / ".cache" / "redline" / f"axe-{AXE_VERSION}.min.js"
STATE_RE = re.compile(r"""data-state\s*[=:,]\s*\\?["'`]?\s*(empty|loading|error)|"""
                      r"""dataset\.state\s*=\s*["'`](empty|loading|error)""")
SMALL_CONTROLS = """() => [...document.querySelectorAll('button,[role=button],input:not([type=hidden]),select,textarea')]
  .filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0 && (r.width < 24 || r.height < 24); })
  .map(e => e.outerHTML.slice(0, 80))"""


def axe_source() -> str:
    if not AXE_CACHE.is_file():
        AXE_CACHE.parent.mkdir(parents=True, exist_ok=True)
        AXE_CACHE.write_text(httpx.get(AXE_URL, timeout=60, follow_redirects=True).raise_for_status().text)
    return AXE_CACHE.read_text()


def states_in(html: str, base_url: str) -> set[str]:
    found = {a or b for a, b in STATE_RE.findall(html)}
    for src in re.findall(r"""<script[^>]+src=["']([^"']+)""", html):
        url = urljoin(base_url + "/", src)
        if urlparse(url).netloc == urlparse(base_url).netloc:
            try:
                found |= {a or b for a, b in STATE_RE.findall(httpx.get(url, timeout=10).text)}
            except httpx.HTTPError:
                pass
    return found


def check(gate: Gate, base_url: str, args) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return gate.finish(False, "playwright is not installed: pip install playwright && playwright install chromium")
    try:
        axe = axe_source()
    except httpx.HTTPError as exc:
        return gate.finish(False, f"could not fetch axe-core once into {AXE_CACHE}: {exc}")
    module = hooks.load(gate.stage_dir)
    routes = args.routes or list(getattr(module, "UI_ROUTES", None) or ["/"])
    login = getattr(module, "ui_login", None)
    shots = gate.evidence / "ui" / f"s{gate.stage}"
    shots.mkdir(parents=True, exist_ok=True)
    host = urlparse(base_url).netloc
    problems, found_states, screenshots = [], set(), []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for width, height in WIDTHS.items():
            context = browser.new_context(viewport={"width": width, "height": height})
            page = context.new_page()
            external = []
            page.route("**/*", lambda route: route.continue_() if urlparse(route.request.url).netloc == host
                       else (external.append(route.request.url), route.abort()))
            if callable(login):
                login(page, base_url)
            for route in routes:
                slug = route.strip("/").replace("/", "_") or "home"
                try:
                    response = page.goto(base_url + route, wait_until="networkidle", timeout=20000)
                except Exception:  # pages that poll never go idle; settle for "load"
                    response = page.goto(base_url + route, wait_until="load", timeout=20000)
                    page.wait_for_timeout(1500)
                if response is None or response.status >= 400:
                    problems.append(f"{route} @{width}: HTTP {response.status if response else 'no response'}")
                    continue
                shot = shots / f"{slug}-{width}.png"
                page.screenshot(path=str(shot), full_page=True)
                screenshots.append(str(shot.relative_to(gate.root)) if shot.is_relative_to(gate.root) else str(shot))
                if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"):
                    problems.append(f"{route} @{width}px: horizontal overflow")
                small = page.evaluate(SMALL_CONTROLS)
                if small:
                    problems.append(f"{route} @{width}px: {len(small)} control(s) under 24px ({small[0]})")
                if width in (375, 1280):
                    page.add_script_tag(content=axe)
                    result = page.evaluate("axe.run(document, {resultTypes: ['violations']})")
                    bad = [v for v in result["violations"] if v.get("impact") in ("serious", "critical")]
                    for v in bad:
                        gate.log(f"axe {route} @{width}: {v['impact']} {v['id']}: {v['help']}")
                    if bad:
                        problems.append(f"{route} @{width}px: {len(bad)} serious axe violation(s) "
                                        f"({', '.join(sorted({v['id'] for v in bad}))})")
                found_states |= states_in(page.content(), base_url)
            if external:
                problems.append(f"@{width}px: {len(external)} asset(s) requested from outside the service "
                                f"({external[0]})")
            context.close()
        browser.close()
    missing = STATES - found_states
    if missing:
        problems.append(f"no data-state marker for: {', '.join(sorted(missing))}")
    gate.log(*problems, f"screenshots: {len(screenshots)} in {shots}")
    detail = "; ".join(dict.fromkeys(problems)) or f"{len(routes)} route(s) clean at 375/768/1280"
    return gate.finish(not problems, detail, screenshots=screenshots, routes=routes)


def main(argv=None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--routes", nargs="*", help="paths to visit (default: hook UI_ROUTES or /)")
    args = parser.parse_args(argv)
    gate = Gate("g7", args)
    return run_gate(gate, args, lambda url: check(gate, url, args))


if __name__ == "__main__":
    raise SystemExit(main())
