"""v0.45: one menu on both pages, the library on seven shelves, and less in front of each desk.

Before this release the core page said Call, Record, Evidence, Method and the full page said Today, Evidence,
Markets, Engine, Library, with the same fifteen desks filed differently on each; the library's index listed 27
of its 50 desks. These tests pin the structure that replaced it: one set of groups, each desk filed once, and
the index, the menu and the map all reading the same list of shelves.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "site" / "src"
NAMES = ["Call", "Record", "Evidence", "Method", "Library"]
KEYS = ["today", "record", "evidence", "engine", "library"]


def _structure():
    boot = (SRC / "boot.js").read_text()
    core = re.search(r"const CORE_GROUPS = \{(.*?)\n  \};", boot, flags=re.S).group(1)
    groups = {k: (n, json.loads("[" + v + "]")) for k, n, v in re.findall(r'(\w+): \{ name: "([^"]+)", views: \[([^\]]+)\] \}', core)}
    block = re.search(r"const SHELVES = \[(.*?)\n  \];", boot, flags=re.S).group(1)
    shelves = [(k, n, json.loads("[" + v + "]")) for k, n, v in re.findall(r'\["(\w+)", "([^"]+)", "[^"]+", \[([^\]]+)\]\]', block)]
    return boot, groups, shelves


def test_one_menu_on_both_pages():
    boot, groups, _ = _structure()
    assert list(groups) == KEYS[:4] and [n for n, _ in groups.values()] == NAMES[:4]
    assert 'const GROUP_ORDER = ["today", "record", "evidence", "engine", "library"];' in boot
    nav = re.search(r'<nav class="tabs".*?</nav>', (SRC / "body.html").read_text(), flags=re.S).group(0)
    assert re.findall(r'data-group="(\w+)">(\w+)</a>', nav) == list(zip(KEYS, NAMES)), "the full page's menu"
    core_nav = re.search(r'CORE_NAV = """(.*?)"""', (ROOT / "scripts" / "assemble_page.py").read_text(), flags=re.S).group(1)
    assert re.findall(r">([A-Za-z]+)</a>", core_nav) == NAMES, "the core page's menu"
    assert re.findall(r'href="#(\w+)" data-group', core_nav) == re.findall(r'href="#(\w+)" data-group', nav)[:4], "each group opens at the same desk"
    # the older menu is gone: no second set of names, and no link that says the reader is on another site
    for gone in ('name: "Today"', 'name: "Markets"', 'name: "Engine"', "core-link", "Core page"):
        assert gone not in boot, gone
    # the core page drops the fifth group and nothing else
    assert "delete GROUPS.library;" in boot and 'const FRONT = CORE ? "home" : "library";' in boot


def test_every_desk_is_filed_once():
    _, groups, shelves = _structure()
    views = re.findall(r'<section class="view" id="view-([\w-]+)"', (SRC / "body.html").read_text())
    core = [v for _, vs in groups.values() for v in vs]
    shelved = [v for _, _, vs in shelves for v in vs]
    filed = core + ["library"] + shelved
    assert len(filed) == len(set(filed)), "a desk is in two places"
    assert set(filed) == set(views) and len(views) == 66
    assert len(shelves) == 7 and len(shelved) == 50 and len(core) == 15
    assert len({k for k, _, _ in shelves}) == 7 and all(2 <= len(vs) <= 9 for _, _, vs in shelves), "a shelf fits one row of sub-tabs"
    # the assembler's list of core desks is the four groups
    asm = (ROOT / "scripts" / "assemble_page.py").read_text()
    assert set(json.loads(re.search(r"CORE_VIEWS = (\[[^\]]+\])", asm).group(1))) == set(core)
    # every desk has a name and a question, so the index never prints a blank line
    names = (SRC / "views.js").read_text().split("const TAB_NAME = ")[1].split("};")[0]
    guide = (SRC / "guide.js").read_text()
    for v in filed:
        assert re.search(rf"\b{v}: \"", names), v
        assert f'"{v}": {{"q": "' in guide, v


def test_index_menu_and_map_read_the_same_shelves():
    boot, book, guide, body = ((SRC / f).read_text() for f in ("boot.js", "book.js", "guide.js", "body.html"))
    assert "const LIBRARY = [" not in book and "SHELVES.forEach(([key, name, sub, views])" in book, "the index reads the shelves"
    assert "const shelf = g === \"library\" ? shelfOf(view) : null;" in boot, "a library desk's sub-tabs are its shelf"
    assert "SHELVES.forEach(([key, name, sub, views])" in guide and 'GROUP_ORDER.filter((gk) => gk !== "library")' in guide, "the map"
    assert "fifty more desks, on seven shelves" in body and "Call, Record, Evidence and Method" in body
    assert 'id="lib-jump"' in body and 'sec.id = "shelf-" + key;' in book
    # the Library tab opens the index, and so does the page with no link
    assert 'a.dataset.group === "library" ? "library"' in boot and "if (!token) return { view: FRONT, el: null };" in boot
    # links written for the older menu still land on a desk
    assert 'const OLD_GROUPS = { markets: "hedges", research: "digest", reference: "appendix" };' in boot


def test_names_and_what_sits_above_each_desk():
    views, guide, body, head = ((SRC / f).read_text() for f in ("views.js", "guide.js", "body.html", "head.html"))
    assert 'desk: "Today\'s call"' in views and 'desk: "Desk"' not in views
    # one line under the headline; the badge and the map button went
    assert '"This desk answers"' in guide and "dguide-lvl" not in guide and "dguide-map" not in guide
    assert 'h("details", "dguide-d")' in guide
    # the line over the headline is written from the menu, so it cannot name a group that no longer exists
    assert "`${GROUPS[groupOf(v)].name} · ${TAB_NAME[v] || v}`" in guide and "`Library · ${sh[1]}`" in guide
    # a desk's contents: a numbered list, not pills
    assert ".toc a::before { content: counter(toc);" in head
    # Home says how the site is laid out, in the menu's order, and every link there is a desk
    home = body[body.index('id="view-home"'):body.index('id="view-track"')]
    lay = home[home.index('id="hm-how-t"'):home.index('class="hm-sign"')]      # v0.47: the "lean investment team" block that followed is gone
    assert "How this site is laid out" in lay and re.findall(r"<h3>(\w+)</h3>", lay) == NAMES
    _, groups, _ = _structure()
    core = {v for _, vs in groups.values() for v in vs}
    links = re.findall(r'href="#(\w+)"', lay)
    assert set(links) - {"library"} == core - {"home"} and "library" in links
    assert "1 to 5 open a group" in guide and "/^[1-5]$/" in views and "<dt>1 to 5</dt><dd>Jump to a group: Call, Record, Evidence, Method, Library</dd>" in body


def test_five_tabs_fit_a_phone():
    head = (SRC / "head.html").read_text()
    phone = head[head.rindex("@media (max-width: 640px) {"):]
    assert ".tabs a { flex: 1 0 auto; justify-content: center; padding: 8px 6px;" in phone
    assert ".subtabs .sub-label.sub-shelf { display: none; }" in phone
    assert "@media (max-width: 900px) { .toc { grid-template-columns: minmax(0, 1fr); } }" in head


def test_version_and_notes():
    import buildout
    assert buildout.__version__ >= "0.45.0"
    assert '["v0.45", "Nov 15, 2026"' in (SRC / "reference.js").read_text() and "Version 0.45:" in (ROOT / "CHANGELOG.md").read_text()
    log = [line for line in (SRC / "memos.js").read_text().splitlines() if '"v0.45"' in line]
    assert len(log) == 1 and "two menus" in log[0] and "27 of its 50" in log[0]
    for p in ("tests/test_v45.py", "site/src/boot.js", "site/src/guide.js", "site/src/book.js"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
