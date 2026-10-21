"""Adversarial browser test for the page: hostile data files, extreme tool inputs, odd viewports,
keyboard-only use, deep links and print. Needs Playwright with Chromium:

    pip install playwright && playwright install chromium
    python site/tests/stress.py            # exits 1 on any failure

It serves site/page.html (wrapped the way GitHub Pages serves it) from temporary folders, one per
data scenario, and fails on any script error, any NaN/undefined/Infinity/null on screen, any horizontal
page scroll, any duplicate id, or any panel that should have rendered but did not. The print scenario
prints every desk to PDF and, when poppler's pdftotext is installed, fails on text printed over text.
The journal scenario writes, locks, unlocks, closes, scores, exports, imports and deletes decisions and
checks they survive a reload. With AXE_JS pointing at axe-core's axe.min.js, every desk is also
checked for serious and critical accessibility violations.
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
import os
import re
import tempfile
import threading
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_site import build  # noqa: E402
import printcheck  # noqa: E402

VIEWS = ["desk", "noteworthy", "decide", "brain", "journal", "swans", "prop", "making", "buyside", "rates", "options", "hedges", "securities", "insurers", "fundamentals", "physics", "findings", "theses",
         "legends", "lenses", "lab", "engine", "appendix", "solve", "games", "field"]
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
          const seen = {}, dup = [];
          document.querySelectorAll("[id]").forEach((e) => { if (seen[e.id]) dup.push(e.id); seen[e.id] = 1; });
          return { overflow: de.scrollWidth - de.clientWidth, bad: hits, view: view && view.id, dup };
        }""", BAD_TEXT)
        if res["dup"]:
            fail(f"{label} #{v}: duplicate ids {sorted(set(res['dup']))[:6]}")
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
    cases.update({
        "fundamentals": [("#dw-life", 2), ("#dw-g", -0.3), ("#dw-life", 7), ("#dw-g", 0.6), ("#dw-co", "CRWV"), ("#dw-co", "ORCL"), ("#dw-life", 4)],
        "physics": [("#ph-capex", 100), ("#ph-cost", 80), ("#ph-load", 0.4), ("#ph-capex", 1500), ("#ph-cost", 25), ("#ph-load", 0.95)],
        "swans": [("#th-p", 0.3), ("#th-crash", -0.7), ("#th-norm", 0), ("#th-cost", 0.05), ("#th-mult", 0), ("#th-mult", 40), ("#th-cost", 0), ("#th-p", 0.02)],
        "lab": [("#lab-coin-f", 0.05), ("#lab-coin-n", 200), ("#lab-coin-f", 1), ("#lab-kelly-p", 0.35), ("#lab-kelly-b", 0.5), ("#lab-kelly-p", 0.85), ("#lab-kelly-b", 4),
                ("#lab-lev-mu", 0.02), ("#lab-lev-sig", 0.6), ("#lab-lev-r", 0.07), ("#lab-lev-sig", 0.05), ("#lab-conj-n", 15), ("#lab-conj-p", 0.5),
                ("#lab-bayes-prior", 0.02), ("#lab-bayes-fpr", 0.5), ("#lab-bayes-sens", 0.99), ("#lab-luck-sr", 0.1), ("#lab-luck-z", 3), ("#lab-div-n", 1), ("#lab-div-rho", 0.95), ("#lab-div-n", 50)],
        "decide": [("#as-a-oil", 0.05), ("#as-a-line", 0.99), ("#as-a-capex", 0.05)],
        "brain": [("#br-size", -3), ("#br-blend", 0), ("#br-K", 1), ("#br-shock", "corr"), ("#br-target", "corr"), ("#br-K", 8), ("#br-blend", 55),
                  ("#br-edge", "y10>eq"), ("#br-w", 1), ("#br-w", -1), ("#br-shock", "pods"), ("#br-target", "hormuz"), ("#br-size", 3)],
        "prop": [("#pe-p", 20), ("#pe-b", 0.3), ("#pe-c", 0.3), ("#pe-r", 20), ("#pe-n", 50), ("#pe-p", 80), ("#pe-b", 5), ("#pe-c", 0),
                 ("#pc-p", 30), ("#pc-b", 0.5), ("#pc-r", 3), ("#pc-days", 10), ("#pc-t", 20), ("#pc-dl", 1), ("#pc-p", 70), ("#pc-b", 3),
                 ("#pp-g", 0), ("#pp-pt", 12), ("#pp-mg", 3), ("#pp-pf", 40), ("#pp-vol", 1)],
        "making": [("#as-sig", 5), ("#as-g", 0.01), ("#as-k", 0.5), ("#as-A", 300), ("#as-g", 1), ("#gm-mu", 0), ("#gm-info", 100), ("#gm-s", 0.5), ("#gm-mu", 50),
                   ("#ex-q", 100), ("#ex-sig", 6), ("#ex-T", 1), ("#ex-l", 0), ("#ex-l", 20), ("#ex-Y", 1.5), ("#ex-q", 0.5), ("#ex-T", 10),
                   ("#fq-qb", 0), ("#fq-qa", 0), ("#fq-pf", 0), ("#fq-pf", 100), ("#fq-miss", 3), ("#fq-later", 100.05), ("#fq-cf", 0.5)],
        "solve": [("#rz-loss", 5), ("#rz-prem", 0), ("#rz-eq", 1.5), ("#rz-h", 1), ("#rz-loss", 35), ("#rz-prem", 2), ("#rz-eq", 0), ("#rz-regime", "low_inflation"),
                  ("#calc-in", "1/0"), ("#calc-in", "foo("), ("#calc-in", "2^1024"), ("#calc-in", "bsput(100, 95, 0.25, ($vix + 3)%)")],
        "games": [("#gt-p", 28), ("#gt-wacc", 13), ("#gt-orcl", 6), ("#gt-p", 70), ("#gt-wacc", 5), ("#gt-crowd", 1500), ("#gt-adv", 10), ("#gt-vol", 6), ("#gt-cost", 150),
                  ("#gt-edge", -2), ("#gt-sdpub", 0.1), ("#gt-sdpriv", 5), ("#gt-edge", 4), ("#gt-sdpub", 5), ("#gt-sdpriv", 0.1), ("#gt-sv", 25), ("#gt-su", 50), ("#gt-order", 2000),
                  ("#gt-preset", "rps"), ("#gt-preset", "stag"), ("#gt-preset", "pennies")],
        "buyside": [("#bd-c", 50), ("#bd-l", 2), ("#bd-l", 7), ("#ce-sh", 0), ("#ce-ni", -500), ("#ce-sh", ""), ("#rd-f", -5), ("#rd-mv", 1e5), ("#rd-f", 1), ("#rd-erp", 1), ("#rd-rf", 2),
                    ("#cs-d", 20), ("#cs-r", 0), ("#cs-m", 2.5), ("#cs-b", 0), ("#cs-d", 0), ("#mb-e", 1e6), ("#mb-p", 0.01), ("#mb-s", 1), ("#mb-atr", 10), ("#mb-e", 10), ("#mb-p", 1e6)],
    })
    for view, steps in cases.items():
        await page.evaluate(f"location.hash = '{view}'")
        await page.wait_for_timeout(300)
        for sel, val in steps:
            await setv(sel, val)
        await page.wait_for_timeout(500)
        for btn in ["#bs-type button[data-v=call]", "#po-strat button[data-k=barbell]", "#po-strat button[data-k=collar]", "#fu-eq button[data-v=NQ]", "#fu-rt button[data-v=ZN]"]:
            if view not in ("options", "hedges") or view == "options" and "fu-" in btn or view == "hedges" and ("bs-" in btn or "po-" in btn):
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
    if await page.evaluate("location.hash") != "#insurers":            # the last Markets desk the reader opened
        fail(f"{label}: key 3 did not reopen the Markets group where the reader left it: {await page.evaluate('location.hash')}")
    await page.evaluate("location.hash = 'options'")
    await page.wait_for_timeout(200)
    await page.keyboard.press("1")
    await page.wait_for_timeout(200)
    await page.keyboard.press("3")
    await page.wait_for_timeout(300)
    if await page.evaluate("location.hash") != "#options":
        fail(f"{label}: the Markets group did not reopen the last desk read in it")
    sub = await page.evaluate("[...document.querySelectorAll('#subtabs a')].map((a) => [a.textContent, a.getAttribute('aria-current')])")
    if ["Options", "page"] not in sub or len(sub) != 7:
        fail(f"{label}: Markets subtabs wrong: {sub}")
    await page.keyboard.press("m")
    on = await page.evaluate("document.documentElement.classList.contains('math-on') && document.getElementById('math-toggle').getAttribute('aria-pressed') === 'true'")
    await page.keyboard.press("M")
    off = await page.evaluate("!document.documentElement.classList.contains('math-on')")
    if not (on and off):
        fail(f"{label}: M did not toggle the math")
    for token, view in [("t3", "theses"), ("sec-tips", "securities"), ("ep-covid-2020", "appendix"), ("pb-credit", "hedges"),
                        ("sig-vix", "desk"), ("g-convexity", "appendix"), ("nope-not-here", "desk"), ("%E0%A4%A", "desk"), ("size", "hedges"),
                        ("faq-is-this-investment-advice", "appendix"), ("d-duration", "decide"), ("as-a-line-row", "decide"), ("ch-oil", "decide"), ("sw-credit", "swans"), ("lg-griffin", "legends"),
                        ("fi-hedge", "findings"), ("lab-coin", "lab"), ("g-hedge-line", "appendix"), ("tl-title", "swans"),
                        ("calc", "solve"), ("rzv-title", "solve"), ("gtc-title", "games"), ("gtx-title", "games"), ("fq-title", "making"), ("pol-title", "engine"), ("g-nash", "appendix"),
                        ("fd-title", "field"), ("fdm-title", "field"), ("brt-title", "brain"), ("field", "field"), ("g-abduction", "appendix"),
                        ("nw-memory", "noteworthy"), ("pr-pods-title", "prop"), ("bs-depr-title", "buyside"), ("brw-title", "brain"), ("g-leontief", "appendix")]:
        await page.evaluate(f"location.hash = {json.dumps(token)}")
        await page.wait_for_timeout(250)
        got = await page.evaluate("document.querySelector('.view:not([hidden])').id")
        if got != "view-" + view:
            fail(f"{label}: #{token} opened {got}, expected {view}")
    opened = await page.evaluate("(() => { location.hash = 'faq-why-does-the-desk-say-bonds-will-not-hedge'; return new Promise((r) => setTimeout(() => r(document.getElementById('faq-why-does-the-desk-say-bonds-will-not-hedge').open), 250)); })()")
    if not opened:
        fail(f"{label}: deep link to a question did not open it")
    await page.evaluate("location.hash = 'desk'")
    await page.keyboard.press("/")
    await page.keyboard.type("inflation line")
    await page.wait_for_timeout(150)
    kinds = await page.evaluate("[...document.querySelectorAll('#palette-list li em')].map((e) => e.textContent)")
    if not {"Finding", "Decision"} & set(kinds):
        fail(f"{label}: search does not reach the v0.5 desks: {kinds}")
    await page.keyboard.press("Escape")


async def print_all(page, label: str) -> None:
    """Print every desk: the PDF holds all eighteen desks with the questions answered, no text lands on
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
    if n < 60:
        fail(f"{label}: only {n} pages printed")
    hits = printcheck.overlaps(str(out))
    if hits:
        fail(f"{label}: text printed over text on pages {sorted({h[0] for h in hits})}: {hits[:4]}")
    blank = printcheck.empty_pages(str(out))
    if blank:
        fail(f"{label}: blank pages {blank}")
    print(f"     printed {n} pages, no text over text")


async def setv(page, sel: str, value) -> None:
    await page.evaluate("([s, v]) => { const el = document.querySelector(s); el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }", [sel, str(value)])


async def journal_flow(page, label: str) -> None:
    """A decision from blank to scored: prefill from the board, lock, unlock, close, export, import, delete, reload."""
    await page.evaluate("location.hash = 'journal'")
    await page.wait_for_timeout(300)
    if await page.evaluate("document.querySelectorAll('#jr-list .jr-item .ex').length") != 6:
        fail(f"{label}: a first visit should show the six examples")
    await page.click("#jr-new")
    await page.select_option("#jr-f-from", "d-duration")
    await page.wait_for_timeout(200)
    filled = await page.evaluate("({ t: document.getElementById('jr-f-title').value, ev: document.getElementById('jr-f-evidence').value.split('\\n').length, as: document.querySelectorAll('#jr-f-as .as-row input[id^=jr-f-as-t]').length })")
    if not filled["t"] or filled["ev"] < 4 or filled["as"] < 3:
        fail(f"{label}: prefill from the board did not fill the entry: {filled}")
    await page.fill("#jr-f-title", "Test: no TLT hedge into the next drawdown")
    await setv(page, "#jr-f-p", 0.62)
    await page.fill("#jr-f-win", "4")
    await page.fill("#jr-f-loss", "2")
    await page.fill("#jr-f-size", "3")
    await page.click("#jr-form .jr-bar .btn")                       # save and lock
    await page.wait_for_timeout(300)
    st = await page.evaluate("({ n: document.querySelectorAll('#jr-list .jr-item:not(:has(.ex))').length, locked: document.getElementById('jr-f-p').disabled, title: document.getElementById('jr-f-title').disabled })")
    if st["n"] != 1 or not st["locked"] or st["title"]:
        fail(f"{label}: saving did not lock the forecast only: {st}")
    kelly = await page.evaluate("document.getElementById('jr-calc').innerText")
    if "Kelly" not in kelly or "NaN" in kelly:
        fail(f"{label}: sizing panel broken: {kelly[:120]}")
    await page.click("#jr-form .jr-bar button:text-is('Unlock the forecast')")
    await page.click("#jr-form .jr-bar button:text-is('Close and review')")
    await page.wait_for_timeout(150)
    await page.fill("#jr-f-ret", "1.5")
    await page.fill("#jr-f-bench_ret", "-2")
    await page.select_option("#jr-f-right", "1")
    await page.click("#jr-form .jr-bar .btn")
    await page.wait_for_timeout(300)
    verdict = await page.evaluate("document.getElementById('jr-verdict') && document.getElementById('jr-verdict').textContent")
    if not verdict or "Alpha" not in verdict:
        fail(f"{label}: closing did not score the decision: {verdict}")
    if await page.evaluate("document.getElementById('jr-f-pr-logged_before').checked"):
        fail(f"{label}: an entry edited after logging still passes the logged-before check")
    await page.click("#jr-ex")                                         # hide the examples: score only mine
    await page.wait_for_timeout(200)
    sub = await page.evaluate("document.getElementById('jrs-sub').textContent")
    if not sub.startswith("1 closed decision"):
        fail(f"{label}: scorecard should count one closed decision: {sub}")
    await page.click("#jr-export")
    await page.wait_for_timeout(200)
    exported = await page.evaluate("document.getElementById('jr-export-text').value")
    try:
        doc = json.loads(exported)
        assert len(doc["decisions"]) == 1 and not doc["decisions"][0].get("example")
    except Exception as exc:  # noqa: BLE001
        fail(f"{label}: export is not a one-decision journal: {exc}")
    tmp = Path(tempfile.mkdtemp(prefix="buildout-journal-")) / "in.json"
    bad = {"decisions": [{"id": "../../etc", "title": "<img src=x onerror=alert(1)>", "p": 7, "win": "lots", "status": "closed", "right": 3, "ret": "x"},
                         {"id": "d-imported-1", "title": "Imported", "p": 0.55, "win": 0.1, "loss": 0.05, "status": "open", "lockedAt": "2026-10-01T00:00:00Z"},
                         {"id": "ex-9", "example": True, "title": "An example must never import"}]}
    tmp.write_text(json.dumps(bad))
    await page.set_input_files("#jr-file", str(tmp))
    await page.wait_for_timeout(500)
    names = await page.evaluate("[...document.querySelectorAll('#jr-list .jr-item strong')].map((e) => e.textContent)")
    if "Imported" not in names or "An example must never import" in names or len(names) != 3:
        fail(f"{label}: import did not clean and add the entries: {names}")
    if await page.evaluate("document.querySelectorAll('#jr-list img').length"):
        fail(f"{label}: an imported title became markup")
    await page.reload(wait_until="load")
    await page.wait_for_timeout(900)
    await page.evaluate("location.hash = 'journal'")
    await page.wait_for_timeout(300)
    if await page.evaluate("document.querySelectorAll('#jr-list .jr-item').length") != 3:
        fail(f"{label}: entries did not survive a reload")
    await page.click("#jr-list .jr-item")
    await page.click("#jr-form .jr-bar button:text-is('Delete')")
    if not await page.evaluate("!!document.querySelector('#jr-confirm .confirm')"):
        fail(f"{label}: delete did not ask in the page")
    await page.click("#jr-confirm button:text-is('Cancel')")
    await page.click("#jr-form .jr-bar button:text-is('Delete')")
    await page.click("#jr-confirm button.danger")
    await page.wait_for_timeout(300)
    if await page.evaluate("document.querySelectorAll('#jr-list .jr-item').length") != 2:
        fail(f"{label}: delete did not remove exactly one entry")


async def live_research(page, label: str) -> None:
    """With research.json from the daily run, the findings, swans and decisions read it instead of the snapshot."""
    await page.evaluate("location.hash = 'findings'")
    await page.wait_for_timeout(400)
    txt = await page.evaluate("document.getElementById('fi-hedge').innerText")
    if "no line validated (no reliable threshold)" not in txt:             # the fixture's planted effect is too weak to validate
        fail(f"{label}: the findings did not switch to the live research file's null result")
    await page.evaluate("location.hash = 'decide'")
    await page.wait_for_timeout(300)
    rule = await page.evaluate("document.querySelector('#d-duration .rule-box').textContent")
    if "none validated today" not in rule:
        fail(f"{label}: decision 2 kept an old line after a null research result: {rule[:160]}")
    note = await page.evaluate("location.hash = 'fundamentals', new Promise((r) => setTimeout(() => r(document.getElementById('fu-note').textContent), 300))")
    if "Newer filings" not in note:
        fail(f"{label}: the newer filing in capex.json was not noted")


async def accessibility(page, label: str) -> None:
    axe = os.environ.get("AXE_JS")
    if not axe or not Path(axe).exists():
        print("     (AXE_JS not set: skipped the accessibility scan)")
        return
    await page.emulate_media(reduced_motion="reduce")     # the desks fade in; measure contrast at rest
    await page.add_script_tag(path=axe)
    for v in VIEWS:
        await page.evaluate(f"location.hash = '{v}'")
        await page.wait_for_timeout(300)
        res = await page.evaluate("""async () => {
          const r = await axe.run(document.querySelector('.view:not([hidden])'), { runOnly: ['wcag2a', 'wcag2aa'], resultTypes: ['violations'] });
          return r.violations.filter((x) => x.impact === 'serious' || x.impact === 'critical').map((x) => x.id + ' (' + x.nodes.length + '): ' + x.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(', '));
        }""")
        if res:
            fail(f"{label} #{v}: accessibility {res[:4]}")


async def main() -> int:
    from fixtures import make_fixtures
    base = make_fixtures(Path(tempfile.mkdtemp(prefix="buildout-fixtures-")))
    good = {n: json.loads((base / n).read_text()) for n in ["macro.json", "report.json", "capex.json", "status.json", "research.json",
                                                             "brain.json", "buyside.json", "feeds.json", "sources.json"]}
    snapshot_only = {k: v for k, v in good.items() if k != "research.json"}
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
    hostile["capex.json"]["ttm"] = {"MSFT": {"quarter_end": "soon", "capex_to_ocf": "high"}, "GOOGL": None, "ZZZ": 5}
    hostile["research.json"] = {"panel": {"months": 12, "end": "2099-01"}, "hedge": {"rows": "many"}}
    hostile["macro.json"]["macro_state"] = {"inflation": {"avg36": "hot", "yoy": None, "date": 5}, "nfci": {"value": "loose"}, "sahm": None}
    hostile["brain.json"]["regimes"]["inflation"]["edges"]["y10>eq"]["w"] = 50
    hostile["buyside.json"]["tail"] = "fat"
    hostile["brain.json"]["factor_cov"] = {"regimes": {"inflation": {"cov": "big", "months": None}, "low_inflation": {"cov": [[1e308]]}}}
    evil = '<img src=x onerror="window.__pwned=1">'
    hostile["feeds.json"]["items"] = [{"title": evil, "url": "javascript:window.__pwned=1", "source": evil, "platform": "<b>x</b>", "tier": "niche", "themes": ["memory"]}]
    hostile["feeds.json"]["themes"][0]["top"] = [{"title": evil, "url": "javascript:window.__pwned=2", "source": evil, "tier": "x"}]
    hostile["feeds.json"]["themes"][0]["series"] = ["a", None, 1e308]
    hostile["feeds.json"]["bluf"] = evil
    huge = copy.deepcopy(good)
    for p in huge["macro.json"]["rates"]["curves"]["latest"]["points"]:
        p["yield"] = 1e6
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        await scenario(browser, "good data", site_with(good), extra=extreme_inputs)
        await scenario(browser, "good data, journal", site_with(good), extra=journal_flow)
        await scenario(browser, "good data, the brain thinks and the field desk", site_with(good), extra=think_and_field)
        await scenario(browser, "good data, live research", site_with(good), extra=live_research)
        newer = copy.deepcopy(good)
        newer["capex.json"]["ttm"]["ORCL"] = {"quarter_end": "2026-11-30", "ocf": 90.0, "capex": 70.0, "cash": 50.0, "capex_to_ocf": 70 / 90}
        await scenario(browser, "a newer filing", site_with(newer), extra=filing_propagation)
        await scenario(browser, "snapshot research", site_with(snapshot_only))
        await scenario(browser, "good data, accessibility", site_with(good), extra=accessibility)
        await scenario(browser, "good data, keyboard and links", site_with(good), extra=keyboard_and_links)
        await scenario(browser, "good data, print every desk", site_with(good), extra=print_all)
        await scenario(browser, "no data at all", site_with(None))
        await scenario(browser, "stale data", site_with(stale), extra=lambda p, l: stale_check(p, l))
        await scenario(browser, "hostile shapes", site_with(hostile), expect_errors=2, extra=no_injection)
        await scenario(browser, "huge yields", site_with(huge))
        await scenario(browser, "truncated files", site_with(None, raw={n: '{"latest": {"as_of": "2026-10' for n in good}))
        await scenario(browser, "incomplete market file", site_with({"macro.json": {"latest": {"as_of": "2026-10-16"}}}), expect_errors=1)
        for w in (320, 768, 1920):
            await scenario(browser, f"good data at {w}px", site_with(good), width=w)
        await browser.close()
    print(f"\n{len(FAILURES)} failures")
    return 1 if FAILURES else 0


async def think_and_field(page, label: str) -> None:
    """v0.8: the brain's reasoning under extreme and missing observations, and the field desk end to end."""
    import re
    def bad_text(txt):
        return [b for b in BAD_TEXT if b in txt] + (["null"] if re.search(r"\bnull\b", txt) else [])
    await page.evaluate("location.hash = 'brain'")
    await page.wait_for_timeout(400)
    await page.click("#br-view button[data-v=think]")
    for node, v in [("capex", 3), ("vix", -3), ("tlt", 3), ("book", -3), ("hormuz", 0)]:
        await setv(page, "#br-obs-node", node)
        await setv(page, "#br-obs-v", v)
        await page.click("#br-obs-add")
    await page.wait_for_timeout(300)
    # remove every observation, then think: the page must say there is nothing to explain, not break
    n = await page.evaluate("""() => { let k = 0; for (let i = 0; i < 60; i++) { const b = document.querySelector('#br-obs button'); if (!b) break; b.click(); k++; } return k; }""")
    await page.click("#br-think-go")
    await page.wait_for_timeout(600)
    txt = await page.evaluate("document.querySelector('#view-brain').innerText")
    if bad_text(txt):
        fail(f"{label}: brain think with {n} observations removed shows {bad_text(txt)}")
    await page.click("#br-obs-reset")
    await page.wait_for_timeout(300)
    if await page.evaluate("document.querySelectorAll('#br-obs tbody tr').length") < 3:
        fail(f"{label}: back to the data did not restore the measured readings")
    # field desk
    await page.evaluate("location.hash = 'field'")
    await page.wait_for_timeout(400)
    for case in ["pipeline", "credit", "leadtime"]:
        await setv(page, "#fd-case", case)
        await page.evaluate("document.querySelectorAll('#fd-ev .fd-row').forEach((r, i) => r.querySelectorAll('button')[1 + (i % 2)].click())")
        await page.wait_for_timeout(150)
        total = await page.evaluate("[...document.querySelectorAll('#fd-post .fd-p b')].reduce((a, b) => a + parseFloat(b.textContent), 0)")
        if not 97 <= total <= 103:
            fail(f"{label}: field case {case} posteriors sum to {total}%")
    evil = '<img src=x onerror="window.__pwned=7">'
    await page.click("#fn-save")
    if "Needed before saving" not in await page.inner_text("#fn-msg"):
        fail(f"{label}: an empty field note was not refused")
    for sel, v in [("#fn-event", "2026-10-10"), ("#fn-learned", "2026-10-01"), ("#fn-entity", evil), ("#fn-claim", evil), ("#fn-resolve", "Q4 filings")]:
        await setv(page, sel, v)
    await page.click("#fn-save")
    if "cannot be before" not in await page.inner_text("#fn-msg"):
        fail(f"{label}: a note learned before the event was accepted")
    await setv(page, "#fn-learned", "2026-10-15")
    await setv(page, "#fn-use", "confidential")
    await page.click("#fn-save")
    if "Confidential" not in await page.inner_text("#fn-msg"):
        fail(f"{label}: confidential material was saved")
    await setv(page, "#fn-use", "public")
    await setv(page, "#fn-node", "power")
    await setv(page, "#fn-z", "99")
    await page.click("#fn-save")
    await page.wait_for_timeout(200)
    obs = await page.evaluate("JSON.parse(localStorage.getItem('bo-brain-obs') || '{}').power")
    if obs != 3:
        fail(f"{label}: a field note's reading reached the brain as {obs}, expected clamped to 3")
    await setv(page, "#ms-t", evil)
    await setv(page, "#ms-due", "2026-01-01")
    await page.click("#ms-add")
    await page.evaluate("localStorage.setItem('bo-field-ms', JSON.stringify(JSON.parse(localStorage.getItem('bo-field-ms')).concat([null, 5, {t: 'x', due: 'soon'}, {t: 'ok', due: '2026-12-01', lag: 1e9}])))")
    await page.evaluate("localStorage.setItem('bo-field-notes', JSON.stringify(JSON.parse(localStorage.getItem('bo-field-notes')).concat([null, 'x', {entity: 5}])))")
    await page.reload()
    await page.wait_for_timeout(900)
    await page.evaluate("location.hash = 'field'")
    await page.wait_for_timeout(500)
    if await page.evaluate("window.__pwned"):
        fail(f"{label}: a field note executed script")
    if await page.evaluate("document.querySelectorAll('#fd-notes tbody tr').length") != 1:
        fail(f"{label}: field notes did not survive a reload cleanly")
    if await page.evaluate("document.querySelectorAll('#fd-ms li').length") != 7:
        fail(f"{label}: milestones after hostile storage: {await page.evaluate('document.querySelectorAll(\"#fd-ms li\").length')}")
    txt = await page.evaluate("document.querySelector('#view-field').innerText")
    if bad_text(txt):
        fail(f"{label}: field desk shows {bad_text(txt)}")


async def filing_propagation(page, label: str) -> None:
    """A newer filing that reverses Oracle's cash coverage must update its table row, coverage label and date together."""
    await page.evaluate("location.hash = 'fundamentals'")
    await page.wait_for_timeout(500)
    row = await page.evaluate("(() => { const r = [...document.querySelectorAll('#fund-table tbody tr')].find((tr) => tr.textContent.includes('Oracle')); return r ? r.textContent : ''; })()")
    if "Self-funded" not in row or "Nov 30, 2026" not in row:
        fail(f"{label}: Oracle's row did not take the newer filing: {row[:200]}")
    await page.evaluate("location.hash = 'games'")
    await page.wait_for_timeout(400)
    cap = await page.evaluate("document.getElementById('gt-capex-table').textContent")
    if "$70.0B" not in cap or "new filing" not in cap:
        fail(f"{label}: the capex game did not use the newer filing")


async def no_injection(page, label: str) -> None:
    """Feed text is untrusted: nothing in it may run, and no javascript: link may reach the page."""
    await page.evaluate("location.hash = 'noteworthy'")
    await page.wait_for_timeout(400)
    res = await page.evaluate("""() => ({ pwned: window.__pwned || 0, imgs: document.querySelectorAll('#view-noteworthy img').length,
      js: [...document.querySelectorAll('a[href]')].filter((a) => a.getAttribute('href').trim().toLowerCase().startsWith('javascript')).length })""")
    if res["pwned"] or res["imgs"] or res["js"]:
        fail(f"{label}: feed content was not inert {res}")


async def stale_check(page, label: str) -> None:
    await page.evaluate("location.hash = 'desk'")
    await page.wait_for_timeout(200)
    n = await page.evaluate("document.querySelectorAll('.badge.stale').length")
    if n == 0:
        fail(f"{label}: no stale badges for data six weeks old")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
