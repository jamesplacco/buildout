"""Adversarial browser test for the page: hostile data files, extreme tool inputs, odd viewports,
keyboard-only use, deep links and print. Needs Playwright with Chromium:

    pip install playwright && playwright install chromium
    python site/tests/stress.py            # exits 1 on any failure

It serves site/page.html (wrapped the way GitHub Pages serves it) from temporary folders, one per
data scenario, and fails on any script error, any NaN/undefined/Infinity/null on screen, any horizontal
page scroll, or any panel that should have rendered but did not. The print scenario prints every desk
to PDF and, when poppler's pdftotext is installed, fails on text printed over text.
"""
from __future__ import annotations

import asyncio
import copy
import functools
import http.server
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import build  # noqa: E402
import printcheck  # noqa: E402

VIEWS = ["desk", "rates", "options", "hedges", "securities", "insurers", "theses", "lenses", "engine", "appendix"]
BAD_TEXT = ["NaN", "undefined", "Infinity", "[object"]
FAILURES: list[str] = []


def fail(msg: str) -> None:
    FAILURES.append(msg)
    print("FAIL", msg)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def serve(folder: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(folder))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/"


def site_with(data: dict[str, object] | None, raw: dict[str, str] | None = None) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="buildout-stress-"))
    src = tmp / "src"
    (src / "data").mkdir(parents=True)
    shutil.copy(ROOT / "site" / "page.html", src / "page.html")
    for name, obj in (data or {}).items():
        (src / "data" / name).write_text(json.dumps(obj))
    for name, text in (raw or {}).items():
        (src / "data" / name).write_text(text)
    build(str(src), str(tmp / "site"))
    return tmp / "site"


async def check_page(page, label: str, views=VIEWS) -> None:
    for v in views:
        await page.evaluate(f"location.hash = '{v}'")
        await page.wait_for_timeout(250)
        res = await page.evaluate("""(bad) => {
          const de = document.documentElement, view = document.querySelector('.view:not([hidden])');
          const txt = view ? view.innerText : '';
          const hits = bad.filter((b) => txt.includes(b));
          if (/\bnull\b/.test(txt)) hits.push("null");
          return { overflow: de.scrollWidth - de.clientWidth, bad: hits, view: view && view.id };
        }""", BAD_TEXT)
        if res["overflow"] > 1:
            fail(f"{label} #{v}: page scrolls sideways by {res['overflow']}px")
        if res["bad"]:
            fail(f"{label} #{v}: shows {res['bad']}")
        if res["view"] != "view-" + v:
            fail(f"{label} #{v}: opened {res['view']}")


async def scenario(browser, label: str, folder: Path, expect_errors: int = 0, width: int = 1280, extra=None) -> None:
    httpd, url = serve(folder)
    ctx = await browser.new_context(viewport={"width": width, "height": 900})
    page = await ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text and "[buildout]" not in m.text else None)
    await page.route("https://fonts.googleapis.com/**", lambda r: r.abort())
    await page.goto(url, wait_until="load")
    await page.wait_for_timeout(1200)
    await check_page(page, label)
    panels = await page.evaluate("document.querySelectorAll('.empty.error').length")
    if panels != expect_errors:
        fail(f"{label}: expected {expect_errors} contained error panels, saw {panels}")
    if extra:
        await extra(page, label)
    if errs:
        fail(f"{label}: script errors {errs[:3]}")
    await ctx.close()
    httpd.shutdown()
    print("ok  ", label)


async def extreme_inputs(page, label: str) -> None:
    async def setv(sel: str, value) -> None:
        await page.evaluate("([s, v]) => { const el = document.querySelector(s); el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", [sel, str(value)])
    cases = {
        "rates": [("#bc-cpn", ""), ("#bc-yld", -5), ("#bc-mat", 50), ("#bc-face", 1e10), ("#bc-shock", 200), ("#bc-yld", "abc"), ("#bc-mat", 0.5), ("#bc-shock", -200),
                  ("#ct-dv01", 5000), ("#ct-d2", 150), ("#ct-d10", -150)],
        "options": [("#bs-S", 0.01), ("#bs-K", 1e7), ("#bs-T", 7), ("#bs-v", 5), ("#bs-r", -5), ("#bs-q", 30), ("#bs-mkt", 0), ("#bs-mkt", 1e7), ("#bs-mkt", ""),
                    ("#bs-S", 100), ("#bs-K", 100), ("#bs-mkt", 5), ("#po-v", 80), ("#po-T", 365), ("#po-v", 8), ("#po-T", 14),
                    ("#tb-k", 98), ("#tb-T", 30), ("#tb-v", 70), ("#tb-n", 150), ("#tb-k", 70), ("#tb-v", 10)],
        "hedges": [("#h-move", -50), ("#h-dy", 200), ("#h-ratio", 150), ("#h-gross", 2), ("#h-y0", 3), ("#h-dur", 18), ("#h-move", 40), ("#h-dy", -200),
                   ("#s-mu", 0), ("#s-sig", 60), ("#s-tv", 5), ("#s-dd", 10), ("#s-conf", "0.99"), ("#s-kf", "1"), ("#s-r", 7), ("#s-sp", 3),
                   ("#fu-book", 10000), ("#fu-beta", 0), ("#fu-ndx", 1000), ("#fu-share", 100), ("#fu-tlt", 0), ("#fu-book", ""), ("#fu-beta", 3), ("#fu-tlt", 100)],
    }
    for view, steps in cases.items():
        await page.evaluate(f"location.hash = '{view}'")
        await page.wait_for_timeout(300)
        for sel, val in steps:
            await setv(sel, val)
        await page.wait_for_timeout(500)
        for btn in ["#bs-type button[data-v=call]", "#po-strat button[data-k=barbell]", "#po-strat button[data-k=collar]", "#fu-eq button[data-v=NQ]", "#fu-rt button[data-v=ZN]"]:
            if view == "options" and "fu-" in btn or view == "hedges" and ("bs-" in btn or "po-" in btn) or view == "rates":
                continue
            await page.click(btn)
        await page.wait_for_timeout(300)
        txt = await page.evaluate("document.querySelector('.view:not([hidden])').innerText")
        bad = [b for b in BAD_TEXT if b in txt] + (["null"] if __import__("re").search(r"\bnull\b", txt) else [])
        if bad:
            fail(f"{label} extreme inputs on #{view}: shows {bad}")


async def keyboard_and_links(page, label: str) -> None:
    await page.evaluate("location.hash = 'desk'")
    await page.wait_for_timeout(200)
    await page.keyboard.press("/")
    if await page.evaluate("document.getElementById('palette').hidden"):
        fail(f"{label}: '/' did not open search")
    await page.keyboard.type("dv01")
    await page.wait_for_timeout(100)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(400)
    if await page.evaluate("location.hash") != "#g-dv01":
        fail(f"{label}: search for dv01 went to {await page.evaluate('location.hash')}")
    await page.keyboard.press("?")
    if await page.evaluate("document.getElementById('keys').hidden"):
        fail(f"{label}: '?' did not open shortcuts")
    await page.keyboard.press("Escape")
    await page.keyboard.press("3")
    await page.wait_for_timeout(300)
    if await page.evaluate("location.hash") != "#options":
        fail(f"{label}: key 3 did not open Options")
    for token, view in [("t3", "theses"), ("sec-tips", "securities"), ("ep-covid-2020", "appendix"), ("faq-12", "appendix"), ("pb-credit", "hedges"),
                        ("sig-vix", "desk"), ("g-convexity", "appendix"), ("nope-not-here", "desk"), ("%E0%A4%A", "desk"), ("size", "hedges")]:
        await page.evaluate(f"location.hash = {json.dumps(token)}")
        await page.wait_for_timeout(250)
        got = await page.evaluate("document.querySelector('.view:not([hidden])').id")
        if got != "view-" + view:
            fail(f"{label}: #{token} opened {got}, expected {view}")
    opened = await page.evaluate("(() => { location.hash = 'faq-12'; return new Promise((r) => setTimeout(() => r(document.getElementById('faq-12').open), 250)); })()")
    if not opened:
        fail(f"{label}: deep link to a question did not open it")


async def print_all(page, label: str) -> None:
    """Print every desk: the PDF holds all ten desks with the questions answered, no text lands on
    text, and the page goes back to the desk and the closed questions the reader had."""
    await page.evaluate("location.hash = 'hedges'")
    await page.wait_for_timeout(300)
    titles = await page.evaluate("[...document.querySelectorAll('.view h1')].map((h) => h.textContent.replace(/\\s+/g, ' ').trim())")
    out = Path(tempfile.mkdtemp(prefix="buildout-print-")) / "all.pdf"
    await page.pdf(path=str(out), format="Letter", print_background=True)
    after = await page.evaluate("({ views: [...document.querySelectorAll('.view')].filter((v) => !v.hidden).map((v) => v.id), open: document.querySelectorAll('.faq details[open]').length, printing: document.body.classList.contains('printing') })")
    if after["views"] != ["view-hedges"] or after["open"] != 0 or after["printing"]:
        fail(f"{label}: page not restored after printing: {after}")
    if not printcheck.available():
        print("     (pdftotext not installed: skipped the print-layout checks)")
        return
    text = " ".join(subprocess.run(["pdftotext", str(out), "-"], capture_output=True, text=True).stdout.split())
    missing = [t for t in titles if t and t[:40] not in text]
    if missing:
        fail(f"{label}: desks missing from the PDF: {missing}")
    n = len(printcheck.pages(str(out)))
    if n < 40:
        fail(f"{label}: only {n} pages printed")
    hits = printcheck.overlaps(str(out))
    if hits:
        fail(f"{label}: text printed over text on pages {sorted({h[0] for h in hits})}: {hits[:4]}")
    blank = printcheck.empty_pages(str(out))
    if blank:
        fail(f"{label}: blank pages {blank}")
    print(f"     printed {n} pages, no text over text")


async def main() -> int:
    from fixtures import make_fixtures
    base = make_fixtures(Path(tempfile.mkdtemp(prefix="buildout-fixtures-")))
    good = {n: json.loads((base / n).read_text()) for n in ["macro.json", "report.json", "capex.json", "status.json"]}
    stale = copy.deepcopy(good)
    stale["macro.json"]["latest"]["as_of"] = "2026-09-01"
    for lv in stale["macro.json"]["rates"]["levels"].values():
        lv["date"] = "2026-09-01"
    hostile = copy.deepcopy(good)
    hostile["macro.json"]["yearly"] = []
    hostile["macro.json"]["corr63"] = {"dates": [], "values": []}
    hostile["macro.json"]["episodes"] = [{"key": "covid-2020", "equity_return": None, "peak": None, "trough": "x"}]
    hostile["macro.json"]["rates"]["curves"]["latest"]["points"] = [{"tenor": "10Y", "years": 10, "yield": None}]
    hostile["macro.json"]["rates"]["levels"]["vix"] = {"value": "high", "date": None}
    hostile["macro.json"]["schema"] = 99
    hostile["capex.json"]["companies"] = {"GOOGL": [{"quarter_end": "2026-06-30", "ocf": None, "capex": None}], "MSFT": []}
    hostile["status.json"]["checks"] = "all good"
    huge = copy.deepcopy(good)
    for p in huge["macro.json"]["rates"]["curves"]["latest"]["points"]:
        p["yield"] = 1e6
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        await scenario(browser, "good data", site_with(good), extra=extreme_inputs)
        await scenario(browser, "good data, keyboard and links", site_with(good), extra=keyboard_and_links)
        await scenario(browser, "good data, print every desk", site_with(good), extra=print_all)
        await scenario(browser, "no data at all", site_with(None))
        await scenario(browser, "stale data", site_with(stale), extra=lambda p, l: stale_check(p, l))
        await scenario(browser, "hostile shapes", site_with(hostile), expect_errors=2)
        await scenario(browser, "huge yields", site_with(huge))
        await scenario(browser, "truncated files", site_with(None, raw={n: '{"latest": {"as_of": "2026-10' for n in good}))
        await scenario(browser, "incomplete market file", site_with({"macro.json": {"latest": {"as_of": "2026-10-16"}}}), expect_errors=1)
        for w in (320, 768, 1920):
            await scenario(browser, f"good data at {w}px", site_with(good), width=w)
        await browser.close()
    print(f"\n{len(FAILURES)} failures")
    return 1 if FAILURES else 0


async def stale_check(page, label: str) -> None:
    await page.evaluate("location.hash = 'desk'")
    await page.wait_for_timeout(200)
    n = await page.evaluate("document.querySelectorAll('.badge.stale').length")
    if n == 0:
        fail(f"{label}: no stale badges for data six weeks old")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
