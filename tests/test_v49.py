"""v0.49: the brief. The front page is five desks for a reader who knows finance and has ten minutes; the library is
the full research, unchanged. These tests pin the shape (five desks, one menu row, what each keeps), that nothing
was deleted (what the brief leaves out is hidden there and whole in the library), that the brief's numbers are the
library's, and that its words stay plain."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
sys.path.insert(0, str(ROOT / "scripts"))
import assemble_page as A  # noqa: E402

BRIEF = ["home", "desk", "book", "track", "explained"]
MENU = ["Home", "Today's call", "Book risk", "Track record", "How it works", "Library"]


def _obj(name: str, text: str) -> str:
    """The body of `const NAME = { ... };` at the top level of a module."""
    return re.search(r"  const " + name + r" = \{(.*?)\n  \};", text, flags=re.S).group(1)


def test_five_desks_and_one_menu_row():
    boot = (SRC / "boot.js").read_text()
    assert A.CORE_VIEWS == BRIEF and json.loads(re.search(r"const BRIEF_VIEWS = (\[[^\]]+\]);", boot).group(1)) == BRIEF
    assert re.findall(r">([A-Za-z' ]+)</a>", A.CORE_NAV) == MENU
    assert re.findall(r'href="#(\w+)" data-group="(\w+)"', A.CORE_NAV) == [(v, v) for v in BRIEF], "each entry is its desk"
    # a group of one has no second row, and the old group links still land on a desk
    assert "if (GROUPS[g].views.length < 2) return;" in boot
    assert 'CORE ? { today: "home", record: "track", evidence: "inventory", engine: "explained" } : {}' in boot
    core = (ROOT / "site" / "core.html").read_text()
    assert re.findall(r'<section class="view" id="view-([a-z0-9]+)"', core) != [] and sorted(re.findall(r'<section class="view" id="view-([a-z0-9]+)"', core)) == sorted(BRIEF)
    # the library is whole: every view, and the four groups it always had
    full = (ROOT / "site" / "page.html").read_text()
    assert len(re.findall(r'<section class="view" id="view-[a-z0-9]+"', full)) == 66
    assert 'const FULL_ORDER = ["today", "record", "evidence", "engine", "library"];' in boot


def test_what_each_desk_keeps_exists_and_the_rest_is_hidden_not_deleted():
    boot, body, head = (SRC / "boot.js").read_text(), (SRC / "body.html").read_text(), (SRC / "head.html").read_text()
    keep = {k: json.loads("[" + v + "]") for k, v in re.findall(r"(\w+): \[([^\]]*)\]", _obj("BRIEF_KEEP", boot))}
    assert set(keep) == {"book", "track", "explained", "desk"}
    made = {"hw-call-title"}          # written by explain.js renderBriefMethod on the brief
    for v, ids in keep.items():
        for i in ids:
            assert i in made or f'id="{i}"' in body, (v, i)
    assert 'h2.id = "hw-call-title";' in (SRC / "explain.js").read_text()
    words = dict(re.findall(r'"([\w-]+)": "([^"]+)"', _obj("BRIEF_WORDS", boot)))
    assert len(words) >= 9 and all(f'id="{i}"' in body for i in words), "every heading the brief rewords is a heading on the page"
    nxt = re.findall(r'\["(\w+)", "[^"]+"\]', _obj("BRIEF_NEXT", boot))
    views = set(re.findall(r'<section class="view" id="view-([\w-]+)"', body))
    assert nxt and all(v in views and v not in BRIEF for v in nxt), "the desks a page points on to are library desks"
    # hidden, whatever a module does to `hidden`; and a link into a hidden part opens the library there
    assert "[data-brief-cut] { display: none !important; }" in head
    assert 'if (el && CORE && el.closest("[data-brief-cut]")) { toLibrary(token);' in boot
    assert "if (CORE || !keep || !root || root.dataset.folded) return;" in boot, "the brief cuts; it does not fold"
    # the library's own copy of each desk is untouched: the brief's wording is a branch, the library's the other
    for f, n in (("today7.js", 4), ("landing.js", 3), ("book.js", 5), ("trackdesk.js", 8)):
        assert (SRC / f).read_text().count("BUILD_CORE") >= n, f


def _node_has_playwright() -> bool:
    try:
        return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


PROBE = r"""
const { chromium } = require("playwright");
(async () => {
  const [core, full] = process.argv.slice(2);
  const b = await chromium.launch();
  const out = { errs: [] };
  const open = async (file, hash) => {
    const p = await b.newPage({ viewport: { width: 1280, height: 900 } });
    p.on("pageerror", (e) => out.errs.push(String(e).slice(0, 200)));
    await p.goto("file://" + file + "#" + hash, { waitUntil: "load" });
    await p.waitForTimeout(1200);
    return p;
  };
  const p = await open(core, "home");
  out.nav = await p.evaluate(() => [...document.querySelectorAll(".tabs a")].map((a) => a.textContent.trim()));
  out.views = {};
  for (const v of ["home", "desk", "book", "track", "explained"]) {
    await p.evaluate((h) => { location.hash = h; }, v);
    await p.waitForTimeout(900);
    out.views[v] = await p.evaluate((v) => {
      const e = document.querySelector("#view-" + v);
      const cut = [...e.querySelectorAll("[data-brief-cut]")];
      return { text: e.innerText, words: e.innerText.split(/\s+/).filter(Boolean).length, cut: cut.length, cutShown: cut.filter((x) => x.offsetParent !== null).length,
        sub: (document.querySelector("#subtabs") || {}).childElementCount || 0, h1: (e.querySelector("h1") || {}).textContent,
        tiles: [...e.querySelectorAll(":scope > .at-tiles .tile, :scope > .at-tiles > *")].map((t) => (t.querySelector("strong, .v, b, dd") || t).textContent.trim()).slice(0, 4),
        more: [...e.querySelectorAll(".brief-more a")].map((a) => a.getAttribute("href")) };
    }, v);
  }
  out.math = await p.evaluate(() => document.documentElement.classList.contains("math-on"));
  // a link into a part the brief hides opens the library there
  await p.evaluate(() => { location.hash = "book"; });
  await p.waitForTimeout(600);
  await p.evaluate(() => { location.hash = "bk-hedge-t"; });
  try { await p.waitForURL("**/page.html#bk-hedge-t", { timeout: 15000 }); out.hiddenLink = true; } catch (e) { out.hiddenLink = p.url(); }
  await p.close();
  const q = await open(full, "desk");
  out.full = { n: await q.evaluate(() => document.querySelectorAll("section.view").length), nav: await q.evaluate(() => [...document.querySelectorAll(".tabs a")].map((a) => a.textContent.trim())) };
  for (const v of ["desk", "book", "track"]) {
    await q.evaluate((h) => { location.hash = h; }, v);
    await q.waitForTimeout(900);
    out.full[v] = await q.evaluate((v) => { const e = document.querySelector("#view-" + v); e.querySelectorAll("details").forEach((d) => { d.open = true; }); return { text: e.innerText, h1: e.querySelector("h1").textContent, cut: e.querySelectorAll("[data-brief-cut]").length }; }, v);
  }
  console.log(JSON.stringify(out));
  await b.close();
})();
"""


@pytest.fixture(scope="module")
def pages(tmp_path_factory):
    if not shutil.which("node") or not _node_has_playwright():
        pytest.skip("no browser here; the daily build's site check covers the pages")
    js = tmp_path_factory.mktemp("v49") / "probe.js"
    js.write_text(PROBE)
    r = subprocess.run(["node", str(js), str(ROOT / "site" / "core.html"), str(ROOT / "site" / "page.html")], capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_the_brief_is_short_and_the_library_is_whole(pages):
    assert pages["errs"] == [] and pages["nav"] == MENU
    v = pages["views"]
    for k in BRIEF:
        assert 150 < v[k]["words"] <= 800, (k, v[k]["words"])
        assert v[k]["cutShown"] == 0 and v[k]["sub"] == 0, k
    assert sum(v[k]["words"] for k in BRIEF) <= 3200, "the whole brief reads in about ten minutes"
    assert all(v[k]["cut"] >= 1 for k in ("desk", "book", "track", "explained")), "each desk leaves something to the library"
    for k in ("desk", "book", "track", "explained"):
        assert v[k]["more"] and v[k]["more"][0] == f"page.html#{k}" and all(h.startswith("page.html#") for h in v[k]["more"]), k
    assert pages["math"] is False, "the formulas are hidden on the brief until asked for"
    assert pages["hiddenLink"] is True, pages["hiddenLink"]
    f = pages["full"]
    assert f["n"] == 66 and f["nav"] == ["Call", "Record", "Evidence", "Method", "Library"]
    assert all(f[k]["cut"] == 0 for k in ("desk", "book", "track")), "nothing is cut in the library"


def test_the_briefs_numbers_are_the_librarys(pages):
    v, f = pages["views"], pages["full"]
    # the call: "53% of full size ... worth 85% of NAV" against "0.53x ... short 85% of NAV"
    size, short = re.search(r"Hold (\d+)% of full size", v["desk"]["h1"]), re.search(r"worth (\d+)% of NAV", v["desk"]["h1"])
    lib = re.search(r"about (\d\.\d\d)x.*short (\d+)% of NAV", f["desk"]["h1"])
    assert size and short and lib, (v["desk"]["h1"], f["desk"]["h1"])
    assert int(size.group(1)) == round(float(lib.group(1)) * 100) and short.group(1) == lib.group(2)
    # the three limits and what the book reads fully invested: each figure in the brief's card is on the library's desk
    card = re.findall(r"\b(\d+)%", v["desk"]["text"].split("The three risk limits.")[1].split("data checks")[0].split("Research desk")[0])
    assert len(card) >= 9
    for n in card:
        assert re.search(rf"(?<![\d.]){n}(\.\d)?%", f["desk"]["text"] + f["book"]["text"]) or re.search(rf"0\.{int(n):02d}x", f["desk"]["text"]), n
    # the record: every percentage and ratio in the brief's four-row table is in the library's table
    rows = v["track"]["text"].split("Return a year\tVolatility")[1].split("The catch")[0]
    nums = re.findall(r"[+−]?\d+(?:\.\d+)?%|\b\d\.\d\d\b", rows)
    assert len(nums) >= 16
    for n in nums:
        base = n.lstrip("+")
        assert base in f["track"]["text"] or re.search(re.escape(base.rstrip("%")) + r"\.\d%", f["track"]["text"]), n


def test_the_words_stay_plain(pages):
    text = "\n".join(pages["views"][k]["text"] for k in BRIEF)
    for jargon in ("expected-shortfall", "evidence gate", "Hidden Markov", "point-in-time", "point in time", "hash", "variance", "factor model", "percentile", "CAGR", "regime", "binds", "gross"):
        assert jargon.lower() not in text.lower(), jargon
    assert not re.search(r"\b\d\.\d\dx\b", text), "sizes are shares of full size on the brief, not multiples"
    assert text.lower().count("walk-forward") <= 2 and text.lower().count("drawdown") <= 1 and text.lower().count("expected shortfall") <= 1, "each term of art is given once, beside its plain name"
    # the method page is how the call is made, in six steps
    ex = pages["views"]["explained"]["text"]
    assert "Six steps, repeated every trading day" in ex and all(s in ex for s in ("Measure the risk.", "Apply the limits.", "Offer the hedged alternative.", "Hedge with bonds only when bonds are hedging.", "Let a forecast move the size only if it has earned it.", "Record the call before it takes effect."))
    for term in ("Full size", "NAV", "Volatility", "Loss in a bad month", "Loss in a bad year", "Beta", "Sharpe ratio"):
        assert term in ex, term
    # honest about what it is: a simulation on stocks picked with hindsight, with the mistakes one link away
    tr, hm = pages["views"]["track"]["text"], pages["views"]["home"]["text"]
    assert "picked with hindsight" in tr and "A simulation, not an account." in hm and "page.html#memos" in pages["views"]["track"]["more"]


def test_readme_is_one_page_and_what_it_carried_is_kept():
    readme = (ROOT / "README.md").read_text()
    assert len(readme.splitlines()) <= 80
    assert "| The rule: hold what the limits allow |" in readme and "candidate list" in readme and "A simulation, not an account" in readme.replace("This is a simulation, not an account", "A simulation, not an account")
    ref = (ROOT / "docs" / "REFERENCE.md").read_text()
    assert "## From the README before v0.49" in ref
    for kept in ("### How the call is produced, and from which data", "### Check it yourself", "### Limits", "gh attestation verify ledger/calls.jsonl"):
        assert kept in ref, kept


def test_version_and_notes():
    import buildout
    assert buildout.__version__ >= "0.49.0"
    assert '["v0.49", "Nov 20, 2026"' in (SRC / "reference.js").read_text() and "Version 0.49:" in (ROOT / "CHANGELOG.md").read_text()
    assert '<span class="ver">v0.49</span>' in (SRC / "body.html").read_text()
    for p in ("tests/test_v49.py", "README.md", "site/src/explain.js"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
