"""v0.43: the core page. The same sources build two pages: site/page.html carries every desk (the library) and
site/core.html carries only the desks the call depends on, without the data and modules only the library uses.

    the core page is a cut, not a copy      it has the core desks and no others, and the full page is unchanged
    nothing a core desk needs is cut        every core desk renders and behaves the same on both pages (in a browser)
    a link never dies                       a desk the core page does not carry opens the library at that desk
    the site publishes both                 index.html is the core page, library.html the full one, each one document
"""
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

CORE = (ROOT / "site" / "core.html").read_text()
FULL = (ROOT / "site" / "page.html").read_text()
PROBE = ROOT / "site" / "tests" / "core_probe.js"


def _views(html: str) -> list[str]:
    return re.findall(r'<section class="view" id="view-([a-z0-9]+)"', html)


def test_both_pages_are_current():
    assert A.assemble() == FULL and A.assemble(core=True) == CORE
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "assemble_page.py"), "--check"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def test_the_core_page_carries_the_core_desks_and_no_others():
    assert sorted(_views(CORE)) == sorted(A.CORE_VIEWS) and len(A.CORE_VIEWS) == 15
    assert len(_views(FULL)) == 66 and set(A.CORE_VIEWS) < set(_views(FULL)), "the full page is the library: every desk"
    boot = (SRC / "boot.js").read_text()
    groups = re.search(r"const CORE_GROUPS = \{(.*?)\n  \};", boot, flags=re.S).group(1)
    in_groups = re.findall(r'"([a-z0-9]+)"', " ".join(re.findall(r"views: \[(.*?)\]", groups)))
    assert sorted(in_groups) == sorted(A.CORE_VIEWS), "the navigation and the markup name the same desks"
    assert "const BUILD_CORE = true;" in CORE and "const BUILD_CORE = false;" in FULL
    nav = re.search(r'<nav class="tabs".*?</nav>', CORE, flags=re.S).group(0)
    assert [m for m in re.findall(r">([A-Za-z]+)</a>", nav)] == ["Call", "Record", "Evidence", "Method", "Library"]
    assert 'href="page.html" class="lib-link"' in nav


def test_the_core_page_is_a_fraction_of_the_full_page():
    assert len(CORE) < 0.30 * len(FULL), f"core {len(CORE):,} bytes against {len(FULL):,}"
    assert len(CORE) < 3_600_000
    stubs = A.core_stubs()
    assert "snap14.js" in stubs and set(stubs["snap14.js"]["raw"]) == {"SNAP14_MIND_JSON", "SNAP14_CODE_JSON"}, "the mind's graph and the embedded source are the library's"
    import prune_core
    assert not (set(stubs) & prune_core.KEEP), "the shared machinery and the core desks' own modules are never left out"
    assert set(stubs) <= set(A.SCRIPTS)
    for name, d in stubs.items():                                      # what is left out is named in the page, so a reader of the source can tell
        if "raw" not in d:
            assert f"/* {name}: not on the core page" in CORE


def test_no_core_module_refers_to_anything_left_out():
    """Rendering the same is necessary, not sufficient: a button the browser check did not press could call a function
    that had become a stand-in. So nothing a core module names may be a stand-in."""
    import prune_core
    stubs = A.core_stubs()
    texts = {n: (SRC / n).read_text() for n in A.SCRIPTS}
    for name, d in stubs.items():
        if "raw" in d or name.startswith("snap"):
            continue
        assert prune_core.used_by_core(d["consts"] + d["funcs"], texts) is None, name


def test_cutting_a_desk_needs_balanced_markup():
    body = '<main>\n<section class="view" id="view-home"><div></div></section>\n<section class="view" id="view-games"><div></section>\n</main>'
    with pytest.raises(SystemExit, match="games desk is not balanced"):
        A.core_body('    <nav class="tabs" aria-label="Sections"></nav>' + body, keep=["home"])
    ok = A.core_body('    <nav class="tabs" aria-label="Sections"></nav><main>\n<section class="view" id="view-home"><p>a</p></section>\n<section class="view" id="view-games"><div></div></section>\n</main>', keep=["home"])
    assert 'id="view-games"' not in ok and 'id="view-home"' in ok and ">Library</a>" in ok
    with pytest.raises(SystemExit, match="core desks missing"):
        A.core_body('    <nav class="tabs" aria-label="Sections"></nav><main>\n<section class="view" id="view-games"><div></div></section>\n</main>', keep=["home"])


def test_a_link_to_a_library_desk_opens_the_library():
    boot = (SRC / "boot.js").read_text()
    assert "if (inLibrary(token)) { toLibrary(token);" in boot and 'location.href = LIBRARY_HREF + "#" + v' in boot
    assert "const ALL_VIEWS = GROUP_ORDER.flatMap" in boot.split("if (CORE) {")[0], "the full list is taken before the groups are swapped"
    v = (SRC / "views.js").read_text()
    assert "BUILD_CORE === true && !(box && box.isConnected)" in v, "a step with no panel on the core page is skipped, not reported as failed"


def _node_has_playwright() -> bool:
    try:
        return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@pytest.fixture(scope="module")
def probes():
    if not shutil.which("node") or not _node_has_playwright():
        pytest.skip("no browser here; the daily build's site check and scripts/prune_core.py cover this")
    out = {}
    for key, page, extra in (("core", "core.html", []), ("full", "page.html", ["--views=" + ",".join(A.CORE_VIEWS)]), ("phone", "core.html", ["--width=390"])):
        r = subprocess.run(["node", str(PROBE), str(ROOT / "site" / page), "--wait=500", "--cut=" + ",".join(A.CORE_CUTS + ["gloss"]), *extra], capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, r.stderr[-800:]
        out[key] = json.loads(r.stdout)
    return out


def test_the_core_page_renders_every_desk_without_an_error(probes):
    c = probes["core"]
    assert c["errs"] == [], c["errs"][:3]
    assert sorted(c["views"]) == sorted(A.CORE_VIEWS)
    for v, x in c["views"].items():
        assert x["shown"] and x["chars"] > 800 and not x["errors"] and not x["used"]["errors"], (v, x)
    assert c["search"] and c["search"] > 3 and c["overflow"] == []
    assert [n[0] for n in c["nav"]] == ["Call", "Record", "Evidence", "Method", "Library"]


def test_every_core_desk_is_the_same_desk_on_both_pages(probes):
    """What was cut was not needed: a core desk's text and behaviour are identical on the core page and on the full
    page, before and after it is used. Left out of the comparison: the guide card on each desk (it names the page's
    own groups), the part of the Desk the core page cuts on purpose, and the glossary, which lists the terms of the
    page it is on."""
    c, f = probes["core"]["views"], probes["full"]["views"]
    for v in A.CORE_VIEWS:
        assert c[v]["body_hash"] == f[v]["body_hash"], f"{v} reads differently on the core page"
        assert c[v]["used"]["body_hash"] == f[v]["used"]["body_hash"], f"{v} behaves differently on the core page"
        if v not in ("desk", "appendix"):
            assert c[v]["rows"] == f[v]["rows"] and c[v]["svgs"] == f[v]["svgs"] and c[v]["used"]["marks"] == f[v]["used"]["marks"], v
    assert c["desk"]["chars"] < 0.6 * f["desk"]["chars"], "the Desk on the core page ends at what would reverse the call"


def test_the_core_page_fits_a_phone(probes):
    p = probes["phone"]
    assert p["errs"] == [] and p["overflow"] == [], p["overflow"]


def test_the_site_publishes_both_pages(tmp_path):
    import build_site
    out = build_site.build(str(ROOT / "site"), str(tmp_path / "_site"))
    index, lib = out.read_text(), (tmp_path / "_site" / "library.html").read_text()
    assert _views(index) and sorted(_views(index)) == sorted(A.CORE_VIEWS) and len(_views(lib)) == 66
    assert '<a href="library.html" class="lib-link"' in index and 'const BUILD_LIBRARY_HREF = "library.html";' in index and 'href="page.html"' not in re.search(r'<nav class="tabs".*?</nav>', index, flags=re.S).group(0)
    for html in (index, lib):
        markup = re.sub(r"<script\b.*?</script>", "", html.lower(), flags=re.S)
        assert markup.count("<!doctype") == 1 and markup.count("<html") == 1 and markup.count("<body>") == 1
    m = json.loads((tmp_path / "_site" / "data" / "manifest.json").read_text())
    assert m["page_bytes"] == len(index.encode()) and m["library_bytes"] == len(lib.encode()) and m["page_bytes"] < 0.3 * m["library_bytes"]


def test_house_style_and_version():
    import buildout
    assert buildout.__version__ >= "0.43.0"
    for p in ("tests/test_v43.py", "scripts/prune_core.py", "scripts/assemble_page.py", "site/tests/core_probe.js"):
        low = (ROOT / p).read_text().lower()
        for b in (chr(0x2014), "inter" "section", "load" "-bearing"):
            assert b not in low, (p, b)
    assert '["v0.43", "Nov 12, 2026"' in (SRC / "reference.js").read_text() and "Version 0.43" in (ROOT / "CHANGELOG.md").read_text()
